import pytest
from django.urls import reverse


# S2 — order_detail must only show the logged-in user's own orders
def test_order_detail_owner_can_view(client, user_a, make_order):
    order = make_order(user_a)
    client.force_login(user_a)
    resp = client.get(reverse('order_detail', args=[order.order_number]))
    assert resp.status_code == 200


def test_order_detail_other_user_gets_404(client, user_a, user_b, make_order):
    order = make_order(user_a)
    client.force_login(user_b)
    resp = client.get(reverse('order_detail', args=[order.order_number]))
    assert resp.status_code == 404
    assert b'Secret street' not in resp.content


# S3 — login must not redirect to an external site taken from the Referer
@pytest.mark.parametrize('next_url', [
    'https://evil.com', '//evil.com', 'https://evil.com/x?a=b',
])
def test_login_ignores_external_next(client, user_a, next_url):
    resp = client.post(
        reverse('login'),
        {'email': 'a@example.com', 'password': 'S3cure-pass-123'},
        HTTP_REFERER=f'http://testserver/accounts/login/?next={next_url}',
    )
    assert resp.status_code == 302
    assert 'evil.com' not in resp['Location']


def test_login_follows_internal_next(client, user_a):
    resp = client.post(
        reverse('login'),
        {'email': 'a@example.com', 'password': 'S3cure-pass-123'},
        HTTP_REFERER='http://testserver/accounts/login/?next=/cart/checkout/',
    )
    assert resp.status_code == 302
    assert resp['Location'] == '/cart/checkout/'


@pytest.mark.parametrize('referer', [
    '', 'http://testserver/accounts/login/', 'http://testserver/accounts/login/?foo=bar',
])
def test_login_without_next_goes_to_dashboard(client, user_a, referer):
    resp = client.post(
        reverse('login'),
        {'email': 'a@example.com', 'password': 'S3cure-pass-123'},
        HTTP_REFERER=referer,
    )
    assert resp.status_code == 302
    assert resp['Location'] == reverse('dashboard')
