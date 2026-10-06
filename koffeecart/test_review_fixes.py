"""Review after phase 7 (V1-V9): each test failed before its fix."""
import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.contrib.sessions.models import Session
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import Account
from carts.models import CartItem
from store.models import ReviewRating, Variation

STRONG = 'S3cure-pass-123'
REGISTER = {
    'first_name': 'New', 'last_name': 'User', 'phone_number': '0900000000',
    'email': 'new@example.com', 'password': STRONG, 'confirm_password': STRONG,
}


def _flash(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


def _count_queries(client, url):
    client.get(url)  # warm up (session, caches)
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(url).status_code == 200
    return len(ctx)


# ---- V1: browsing anonymously must not create a database session on every page ----
def test_anonymous_browsing_creates_no_session(client, product):
    for url in (reverse('home'), reverse('store'), product.get_url(), reverse('cart')):
        resp = client.get(url)
        assert resp.status_code == 200
        assert settings.SESSION_COOKIE_NAME not in resp.cookies, url
    assert Session.objects.count() == 0


def test_guest_gets_a_session_once_they_add_to_cart(client, product):
    client.post(reverse('add_cart', args=[product.id]))
    assert Session.objects.count() == 1
    assert client.get(reverse('cart')).context['cart_count'] == 1


# ---- V2: the cart cannot hold more than the stock ----
def test_cannot_add_sold_out_product(client, make_product):
    sold_out = make_product(stock=0)
    resp = client.post(reverse('add_cart', args=[sold_out.id]))
    assert resp.status_code == 302 and resp['Location'] == sold_out.get_url()
    assert not CartItem.objects.exists()
    assert any('stock' in m for m in _flash(resp))


def test_cannot_add_more_than_stock(client, make_product):
    last_one = make_product(stock=1)
    client.post(reverse('add_cart', args=[last_one.id]))
    resp = client.post(reverse('add_cart', args=[last_one.id]))
    assert resp['Location'] == reverse('cart')
    assert CartItem.objects.get().quantity == 1


# ---- V3: the same variations in a different order are the same cart line ----
def test_variation_order_does_not_split_cart_lines(client, product):
    Variation.objects.create(product=product, variation_category='color', variation_value='red')
    Variation.objects.create(product=product, variation_category='size', variation_value='500g')
    client.post(reverse('add_cart', args=[product.id]), {'color': 'red', 'size': '500g'})
    client.post(reverse('add_cart', args=[product.id]), {'size': '500g', 'color': 'red'})
    line = CartItem.objects.get()
    assert line.quantity == 2


# ---- V4 / V8: pages listing several lines run a fixed number of queries ----
def _fill_cart(user, make_product, n):
    for _ in range(n):
        p = make_product()
        v = Variation.objects.create(product=p, variation_category='size', variation_value='250g')
        line = CartItem.objects.create(user=user, product=p, quantity=1)
        line.variations.add(v)


@pytest.mark.parametrize('url_name', ['cart', 'checkout'])
def test_cart_pages_query_count_does_not_grow(client, user_a, make_product, url_name):
    client.force_login(user_a)
    _fill_cart(user_a, make_product, 2)
    few = _count_queries(client, reverse(url_name))
    _fill_cart(user_a, make_product, 4)
    assert _count_queries(client, reverse(url_name)) == few


def _placed_order(client, user, make_product, n):
    from orders.models import Order
    _fill_cart(user, make_product, n)
    client.post(reverse('place_order'), {
        'first_name': 'A', 'last_name': 'B', 'phone': '1', 'email': 'a@example.com',
        'address_line_1': 'x', 'city': 'c', 'state': 's', 'country': 'VN'})
    order = Order.objects.filter(user=user).latest('id')
    client.post(reverse('payments'), {'orderID': order.order_number})
    order.refresh_from_db()
    return order


def test_order_pages_query_count_does_not_grow(client, user_a, make_product):
    client.force_login(user_a)
    small = _placed_order(client, user_a, make_product, 2)
    big = _placed_order(client, user_a, make_product, 5)
    for view in ('order_detail',):
        assert (_count_queries(client, reverse(view, args=[small.order_number]))
                == _count_queries(client, reverse(view, args=[big.order_number])))
    complete = reverse('order_complete') + '?order_number={}&payment_id={}'
    assert (_count_queries(client, complete.format(small.order_number, small.payment.payment_id))
            == _count_queries(client, complete.format(big.order_number, big.payment.payment_id)))


def test_product_reviews_query_count_does_not_grow(client, product):
    def add_reviews(n):
        for _ in range(n):
            i = Account.objects.count()
            user = Account.objects.create_user(first_name='R', last_name=str(i), username=f'r{i}',
                                               email=f'r{i}@example.com', password=STRONG)
            ReviewRating.objects.create(product=product, user=user, rating=4)
    add_reviews(2)
    few = _count_queries(client, product.get_url())
    add_reviews(4)
    assert _count_queries(client, product.get_url()) == few


# ---- V5: links in emails use https when the site is served over https ----
def test_activation_link_uses_https_on_secure_requests(client, db):
    client.post(reverse('register'), REGISTER, secure=True)
    assert 'https://testserver/accounts/activate/' in mail.outbox[0].body


def test_reset_link_uses_http_on_plain_requests(client, user_a):
    client.post(reverse('forgotPassword'), {'email': 'a@example.com'})
    assert 'http://testserver/accounts/resetpassword_validate/' in mail.outbox[0].body


# ---- V6: email addresses are case-insensitive ----
def test_register_rejects_same_email_in_other_case(client, user_a):
    resp = client.post(reverse('register'), dict(REGISTER, email='A@Example.com'))
    assert resp.status_code == 200
    assert Account.objects.filter(email__iexact='a@example.com').count() == 1


def test_login_email_is_case_insensitive(client, user_a):
    resp = client.post(reverse('login'), {'email': 'A@EXAMPLE.com', 'password': STRONG})
    assert resp['Location'] == reverse('dashboard')


def test_forgot_password_email_is_case_insensitive(client, user_a):
    client.post(reverse('forgotPassword'), {'email': 'A@Example.COM'})
    assert len(mail.outbox) == 1


# ---- V7: "next" survives login without relying on the Referer header ----
def test_login_page_carries_next(client, db):
    html = client.get(reverse('login') + '?next=/cart/checkout/').content.decode()
    assert '<input type="hidden" name="next" value="/cart/checkout/">' in html


@pytest.mark.parametrize('next_url, expected', [
    ('/cart/checkout/', '/cart/checkout/'),
    ('https://evil.example/', '/accounts/dashboard/'),
    ('//evil.example/', '/accounts/dashboard/'),
])
def test_login_follows_posted_next_when_safe(client, user_a, next_url, expected):
    resp = client.post(reverse('login'), {'email': 'a@example.com', 'password': STRONG, 'next': next_url})
    assert resp['Location'] == expected


# ---- V9: mails are sent from a real sender, not webmaster@localhost ----
def test_mail_sender_is_configured(client, user_a):
    client.post(reverse('forgotPassword'), {'email': 'a@example.com'})
    assert mail.outbox[0].from_email != 'webmaster@localhost'
    assert 'KoffeeCart' in mail.outbox[0].from_email


# ---- admin: every registered model's list and add pages open, and read well ----
@pytest.fixture
def admin_client(client, db):
    admin = Account.objects.create_superuser(
        first_name='Ad', last_name='Min', email='admin@example.com', username='admin', password=STRONG)
    client.force_login(admin)
    return client


def test_every_admin_page_opens(admin_client, user_a, product, make_order):
    from django.contrib import admin
    order = make_order(user_a)
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    ReviewRating.objects.create(product=product, user=user_a, rating=4)
    for model in admin.site._registry:
        meta = model._meta
        for page in ('changelist', 'add'):
            url = reverse(f'admin:{meta.app_label}_{meta.model_name}_{page}')
            assert admin_client.get(url).status_code == 200, url
    assert admin_client.get(reverse('admin:orders_order_change', args=[order.id])).status_code == 200


def test_cart_item_has_a_readable_name(user_a, product):
    line = CartItem.objects.create(user=user_a, product=product, quantity=2)
    assert str(line) == '2 x Arabica'


def test_payment_admin_shows_status(admin_client, user_a, make_order):
    make_order(user_a)
    html = admin_client.get(reverse('admin:orders_payment_changelist')).content.decode()
    assert 'COMPLETED' in html and 'PAY-202601011' in html
