"""Review round 2 (W1-W6) and SEO basics: each bug test failed before its fix."""
import pytest
from django.contrib.messages import get_messages
from django.core import mail
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import Account
from carts.models import CartItem
from orders.models import Order, OrderProduct, Payment
from store.models import ReviewRating

STRONG = 'S3cure-pass-123'
CHECKOUT_FORM = {
    'first_name': 'An', 'last_name': 'Nguyen', 'phone': '0900000000', 'email': 'a@example.com',
    'address_line_1': '1 Coffee St', 'city': 'Ha Noi', 'state': 'HN', 'country': 'VN',
}


def _flash(resp):
    return ' '.join(str(m) for m in get_messages(resp.wsgi_request))


def _hide(product):
    product.is_available = False
    product.save()


# ---- W1: a hidden product cannot be seen, added or bought ----
def test_hidden_product_page_is_404(client, product):
    _hide(product)
    assert client.get(product.get_url()).status_code == 404


def test_hidden_product_cannot_be_added(client, product):
    _hide(product)
    assert client.post(reverse('add_cart', args=[product.id])).status_code == 404
    assert not CartItem.objects.exists()


def test_hidden_product_cannot_be_ordered(client, user_a, product, order_with_cart):
    order = order_with_cart(user_a)
    _hide(product)  # hidden after it went into the cart
    client.force_login(user_a)
    resp = client.post(reverse('payments'), {'orderID': order.order_number})
    assert resp.status_code == 302 and resp['Location'] == reverse('cart')
    assert 'no longer available' in _flash(resp)
    order.refresh_from_db()
    product.refresh_from_db()
    assert order.is_ordered is False and product.stock == 5


def test_cart_flags_hidden_products(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    _hide(product)
    client.force_login(user_a)
    assert 'No longer available' in client.get(reverse('cart')).content.decode()


# ---- W2: checking out again does not leave a trail of unpaid orders ----
def test_place_order_replaces_the_previous_unpaid_order(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    client.post(reverse('place_order'), CHECKOUT_FORM)
    client.post(reverse('place_order'), CHECKOUT_FORM)
    assert Order.objects.filter(user=user_a, is_ordered=False).count() == 1


def test_place_order_keeps_placed_orders(client, user_a, product, make_order):
    placed = make_order(user_a, number='P1', paid=True)
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    client.post(reverse('place_order'), CHECKOUT_FORM)
    assert Order.objects.filter(pk=placed.pk).exists()


# ---- W3: one review per customer and product, enforced by the database ----
def test_second_review_by_same_user_is_refused_by_the_db(user_a, product):
    ReviewRating.objects.create(product=product, user=user_a, rating=4)
    with pytest.raises(IntegrityError), transaction.atomic():
        ReviewRating.objects.create(product=product, user=user_a, rating=2)


# ---- W4: cancelling an order gives the stock back, once ----
@pytest.fixture
def placed(client, user_a, product):
    """A real order for 2 units placed through checkout (stock 5 -> 3)."""
    CartItem.objects.create(user=user_a, product=product, quantity=2)
    client.force_login(user_a)
    client.post(reverse('place_order'), CHECKOUT_FORM)
    order = Order.objects.get(user=user_a)
    client.post(reverse('payments'), {'orderID': order.order_number})
    order.refresh_from_db()
    product.refresh_from_db()
    assert order.is_ordered and product.stock == 3
    return order


def test_cancel_restocks_once(placed, product):
    assert placed.cancel() is True
    assert placed.cancel() is False  # already cancelled: nothing happens
    product.refresh_from_db()
    placed.refresh_from_db()
    assert product.stock == 5
    assert placed.status == 'Cancelled'
    assert placed.payment.status == 'Cancelled'


def test_customer_can_cancel_a_new_order(client, placed, product):
    resp = client.post(reverse('cancel_order', args=[placed.order_number]))
    assert resp.status_code == 302
    placed.refresh_from_db()
    product.refresh_from_db()
    assert placed.status == 'Cancelled' and product.stock == 5


def test_customer_cannot_cancel_an_accepted_order(client, placed, product):
    placed.status = 'Accepted'
    placed.save()
    client.post(reverse('cancel_order', args=[placed.order_number]))
    placed.refresh_from_db()
    product.refresh_from_db()
    assert placed.status == 'Accepted' and product.stock == 3


def test_customer_cannot_cancel_someone_elses_order(client, placed, user_b):
    client.force_login(user_b)
    assert client.post(reverse('cancel_order', args=[placed.order_number])).status_code == 404


def test_cancel_needs_post(client, placed):
    assert client.get(reverse('cancel_order', args=[placed.order_number])).status_code == 405


def _admin(client):
    admin = Account.objects.create_superuser(
        first_name='Ad', last_name='Min', email='admin@example.com', username='admin', password=STRONG)
    client.force_login(admin)


def test_admin_cancelling_from_the_list_restocks(client, placed, product):
    _admin(client)
    url = reverse('admin:orders_order_changelist')
    data = {
        'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '0',
        'form-MAX_NUM_FORMS': '1000', 'form-0-id': str(placed.pk), 'form-0-status': 'Cancelled',
        '_save': 'Save',
    }
    assert client.post(url, data).status_code == 302
    product.refresh_from_db()
    placed.refresh_from_db()
    assert placed.status == 'Cancelled' and product.stock == 5


def test_admin_cannot_reopen_a_cancelled_order(client, placed, product):
    placed.cancel()
    _admin(client)
    data = {
        'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '0',
        'form-MAX_NUM_FORMS': '1000', 'form-0-id': str(placed.pk), 'form-0-status': 'New',
        '_save': 'Save',
    }
    client.post(reverse('admin:orders_order_changelist'), data)
    placed.refresh_from_db()
    product.refresh_from_db()
    assert placed.status == 'Cancelled' and product.stock == 5  # stock not taken twice


def test_admin_bulk_cancel_action(client, placed, product):
    _admin(client)
    client.post(reverse('admin:orders_order_changelist'),
                {'action': 'cancel_orders', '_selected_action': [placed.pk]})
    product.refresh_from_db()
    assert product.stock == 5


# ---- W5: the order email lists what was bought and links to the order ----
def test_order_email_has_items_total_and_link(placed, product):
    body = mail.outbox[-1].body
    assert product.product_name in body
    assert str(placed.order_total) in body
    assert f'/accounts/order_detail/{placed.order_number}/' in body
    assert 'Cash on delivery' in body


# ---- W6: order numbers are strings, not only digits ----
def test_order_detail_url_accepts_any_order_number(client, user_a, make_order):
    order = make_order(user_a, number='DEMO0001')
    client.force_login(user_a)
    resp = client.get(reverse('order_detail', args=[order.order_number]))
    assert resp.status_code == 200
    assert 'DEMO0001' in client.get(reverse('my_orders')).content.decode()


# ---- SEO basics ----
def test_robots_txt(client, db):
    resp = client.get('/robots.txt')
    assert resp.status_code == 200 and resp['Content-Type'].startswith('text/plain')
    body = resp.content.decode()
    assert 'Disallow: /securelogin/' in body and 'Sitemap: http://testserver/sitemap.xml' in body


def test_sitemap_lists_available_products_only(client, make_product):
    shown = make_product()
    hidden = make_product()
    _hide(hidden)
    body = client.get('/sitemap.xml').content.decode()
    assert shown.get_url() in body and hidden.get_url() not in body
    assert reverse('store') in body


def test_product_page_has_meta_description(client, product):
    product.description = 'Bold and chocolatey.'
    product.save()
    html = client.get(product.get_url()).content.decode()
    assert '<meta name="description" content="Bold and chocolatey.">' in html
    assert '<meta property="og:title" content="Arabica">' in html


def test_payment_rows_survive_cancellation(placed):
    placed.cancel()
    assert Payment.objects.filter(pk=placed.payment_id).exists()
    assert OrderProduct.objects.filter(order=placed).count() == 1
