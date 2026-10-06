import json
from decimal import Decimal

import pytest
from django.urls import reverse

from carts.models import CartItem
from orders.models import Order, Payment


# S4 — anonymous users must be sent to login, not hit a 500
def test_place_order_requires_login(client):
    resp = client.post(reverse('place_order'), {})
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_payments_requires_login(client):
    resp = client.post(reverse('payments'), data=json.dumps({}),
                       content_type='application/json')
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_order_complete_requires_login(client):
    resp = client.get(reverse('order_complete'))
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_payments_rejects_get(client, user_a):
    client.force_login(user_a)
    assert client.get(reverse('payments')).status_code == 405


# order_complete must not show another user's order
def test_order_complete_owner_sees_order(client, user_a, make_order):
    order = make_order(user_a)
    client.force_login(user_a)
    resp = client.get(reverse('order_complete'), {
        'order_number': order.order_number, 'payment_id': order.payment.payment_id})
    assert resp.status_code == 200


def test_order_complete_other_user_redirected(client, user_a, user_b, make_order):
    order = make_order(user_a)
    client.force_login(user_b)
    resp = client.get(reverse('order_complete'), {
        'order_number': order.order_number, 'payment_id': order.payment.payment_id})
    assert resp.status_code == 302
    assert resp['Location'] == reverse('home')


# ---- S1 / B2 / B6: COD payment is decided by the server, not by the client ----
def _pay(client, **data):
    return client.post(reverse('payments'), data)


def test_old_forged_json_payment_is_rejected(client, user_a, product, order_with_cart):
    """The original S1 attack: JSON body claiming status COMPLETED."""
    order = order_with_cart(user_a)
    client.force_login(user_a)
    resp = client.post(
        reverse('payments'),
        data=json.dumps({'orderID': order.order_number, 'transID': 'FAKE',
                         'payment_method': 'PayPal', 'status': 'COMPLETED'}),
        content_type='application/json')
    assert resp.status_code == 400
    order.refresh_from_db()
    product.refresh_from_db()
    assert order.is_ordered is False
    assert product.stock == 5
    assert not Payment.objects.filter(payment_id='FAKE').exists()


def test_cod_payment_ignores_client_supplied_fields(client, user_a, product, order_with_cart):
    order = order_with_cart(user_a)
    client.force_login(user_a)
    resp = _pay(client, orderID=order.order_number, transID='FAKE',
                status='COMPLETED', payment_method='PayPal', amount='0.01')
    assert resp.status_code == 302
    order.refresh_from_db()
    assert order.is_ordered is True
    assert order.payment.payment_method == 'COD'
    assert order.payment.status == 'Pending'
    assert order.payment.payment_id != 'FAKE'
    assert order.payment.amount_paid == order.order_total
    product.refresh_from_db()
    assert product.stock == 4
    assert not CartItem.objects.filter(user=user_a).exists()
    assert order.orderproduct_set.count() == 1


@pytest.mark.parametrize('data', [{}, {'orderID': ''}, {'orderID': 'nope'}])
def test_payments_bad_input_returns_400(client, user_a, order_with_cart, data):
    order_with_cart(user_a)
    client.force_login(user_a)
    assert _pay(client, **data).status_code == 400


def test_payments_empty_body_returns_400(client, user_a):
    client.force_login(user_a)
    resp = client.post(reverse('payments'), data='', content_type='application/json')
    assert resp.status_code == 400


def test_cannot_pay_someone_elses_order(client, user_a, user_b, product, order_with_cart):
    order = order_with_cart(user_a)
    client.force_login(user_b)
    assert _pay(client, orderID=order.order_number).status_code == 400
    order.refresh_from_db()
    assert order.is_ordered is False


def test_insufficient_stock_rolls_back_everything(client, user_a, product, order_with_cart):
    order = order_with_cart(user_a, qty=6)  # stock is 5
    client.force_login(user_a)
    resp = _pay(client, orderID=order.order_number)
    assert resp.status_code == 302
    assert resp['Location'] == reverse('cart')
    order.refresh_from_db()
    product.refresh_from_db()
    assert order.is_ordered is False
    assert order.payment is None
    assert product.stock == 5
    assert CartItem.objects.filter(user=user_a).exists()
    assert Payment.objects.count() == 0


def test_double_submit_charges_stock_once(client, user_a, product, order_with_cart):
    order = order_with_cart(user_a)
    client.force_login(user_a)
    assert _pay(client, orderID=order.order_number).status_code == 302
    assert _pay(client, orderID=order.order_number).status_code == 400
    product.refresh_from_db()
    assert product.stock == 4
    assert Payment.objects.count() == 1


def test_email_failure_does_not_break_order(client, user_a, order_with_cart, monkeypatch):
    from django.core.mail import EmailMessage

    def boom(self, *a, **k):
        raise OSError('smtp down')
    monkeypatch.setattr(EmailMessage, 'send', boom)
    order = order_with_cart(user_a)
    client.force_login(user_a)
    assert _pay(client, orderID=order.order_number).status_code == 302
    order.refresh_from_db()
    assert order.is_ordered is True


# ---- B4: an invalid billing form re-renders checkout with errors (used to return None -> 500) ----
GOOD_FORM = {
    'first_name': 'An', 'last_name': 'Nguyen', 'phone': '0900000000',
    'email': 'an@example.com', 'address_line_1': '1 Coffee St', 'address_line_2': '',
    'city': 'Saigon', 'state': 'HCM', 'country': 'VN', 'order_note': '',
}


def test_place_order_invalid_form_rerenders_checkout(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    bad = dict(GOOD_FORM, phone='1' * 40, first_name='')
    resp = client.post(reverse('place_order'), bad)
    assert resp.status_code == 200
    assert 'store/checkout.html' in [t.name for t in resp.templates]
    assert Order.objects.count() == 0
    assert b'Ensure this value has at most 15 characters' in resp.content
    # what the user already typed is kept, so they only fix the wrong fields
    assert b'value="Saigon"' in resp.content


def test_place_order_valid_form_stores_exact_decimal_money(client, user_a, make_product):
    p = make_product(price='19.99')
    CartItem.objects.create(user=user_a, product=p, quantity=3)
    client.force_login(user_a)
    resp = client.post(reverse('place_order'), GOOD_FORM)
    assert resp.status_code == 200
    order = Order.objects.get()
    assert order.is_ordered is False
    assert order.tax == Decimal('1.20')
    assert order.order_total == Decimal('61.17')


def test_completed_order_keeps_decimal_prices(client, user_a, make_product):
    p = make_product(price='19.99')
    CartItem.objects.create(user=user_a, product=p, quantity=3)
    client.force_login(user_a)
    client.post(reverse('place_order'), GOOD_FORM)
    order = Order.objects.get()
    assert _pay(client, orderID=order.order_number).status_code == 302
    order.refresh_from_db()
    assert order.payment.amount_paid == Decimal('61.17')
    assert order.orderproduct_set.get().product_price == Decimal('19.99')


# ---- the "order placed" page shows what was ordered (it used to render empty tables) ----
def test_order_complete_page_shows_order_details(client, user_a, make_product):
    p = make_product(price='19.99')
    CartItem.objects.create(user=user_a, product=p, quantity=3)
    client.force_login(user_a)
    client.post(reverse('place_order'), GOOD_FORM)
    order = Order.objects.get()
    resp = client.post(reverse('payments'), {'orderID': order.order_number}, follow=True)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert order.order_number in html
    assert p.product_name in html
    assert '59.97' in html and '1.20' in html and '61.17' in html
    assert 'Cash on delivery' in html
    assert 'Make Payment' not in html


# ---- R1: the total is fixed at place_order; a cart changed afterwards must not be placed ----
def test_cart_changed_after_place_order_is_not_placed(client, user_a, product, make_product, order_with_cart):
    order = order_with_cart(user_a)
    extra = make_product(price='50.00', stock=10)
    CartItem.objects.create(user=user_a, product=extra, quantity=1)  # added in another tab
    client.force_login(user_a)

    resp = _pay(client, orderID=order.order_number)

    assert resp.status_code == 302 and resp['Location'] == reverse('checkout')
    order.refresh_from_db()
    extra.refresh_from_db()
    product.refresh_from_db()
    assert order.is_ordered is False
    assert (extra.stock, product.stock) == (10, 5)
    assert Payment.objects.count() == 0
    assert CartItem.objects.filter(user=user_a).count() == 2  # cart kept, so the user can check out again


def test_unchanged_cart_is_placed_with_matching_total(client, user_a, product, order_with_cart):
    order = order_with_cart(user_a, qty=2)
    client.force_login(user_a)
    assert _pay(client, orderID=order.order_number).status_code == 302
    order.refresh_from_db()
    assert order.is_ordered is True
    assert order.payment.amount_paid == order.order_total == Decimal('204.00')
