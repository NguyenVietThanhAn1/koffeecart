import json

from django.urls import reverse


def _login_url(path):
    return reverse('login') + '?next=' + path


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
import pytest
from carts.models import CartItem
from orders.models import Order, Payment


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
    assert order.payment.amount_paid == str(order.order_total)
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
