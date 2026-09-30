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
