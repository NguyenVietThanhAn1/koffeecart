from smtplib import SMTPException

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.contrib.messages import get_messages
from django.core import mail
from django.core.mail import EmailMessage
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Account

STRONG = 'S3cure-pass-123'
NEW_STRONG = 'An0ther-Str0ng-pass'
REGISTER = {
    'first_name': 'New', 'last_name': 'User', 'phone_number': '0900000000',
    'email': 'new@example.com', 'password': STRONG, 'confirm_password': STRONG,
}


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


def _flash(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


def _boom(self, *args, **kwargs):
    raise SMTPException('smtp down')


# ---- S6: passwords must pass Django's validators everywhere they are set ----
def test_register_rejects_weak_password(client, db):
    resp = client.post(reverse('register'), dict(REGISTER, password='a', confirm_password='a'))
    assert resp.status_code == 200
    assert not Account.objects.filter(email='new@example.com').exists()
    assert b'too short' in resp.content


def test_register_accepts_strong_password(client, db):
    resp = client.post(reverse('register'), REGISTER)
    assert resp.status_code == 302
    assert Account.objects.get(email='new@example.com').is_active is False
    assert len(mail.outbox) == 1


def test_register_redirect_encodes_the_email(client, db):
    resp = client.post(reverse('register'), dict(REGISTER, email='new+tag@example.com'))
    assert resp.status_code == 302
    assert 'email=new%2Btag%40example.com' in resp['Location']


def _start_reset(client, user):
    session = client.session
    session['uid'] = str(user.pk)
    session.save()


def test_reset_password_rejects_weak_password(client, user_a):
    _start_reset(client, user_a)
    resp = client.post(reverse('resetPassword'), {'password': 'a', 'confirm_password': 'a'})
    assert resp.status_code == 302 and resp['Location'] == reverse('resetPassword')
    user_a.refresh_from_db()
    assert user_a.check_password(STRONG)  # unchanged


def test_reset_password_accepts_strong_password_and_clears_uid(client, user_a):
    _start_reset(client, user_a)
    resp = client.post(reverse('resetPassword'),
                       {'password': NEW_STRONG, 'confirm_password': NEW_STRONG})
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
    user_a.refresh_from_db()
    assert user_a.check_password(NEW_STRONG)
    assert 'uid' not in client.session  # the reset session cannot be reused


def test_reset_password_link_flow(client, user_a):
    uid = urlsafe_base64_encode(force_bytes(user_a.pk))
    token = default_token_generator.make_token(user_a)
    resp = client.get(reverse('resetpassword_validate', args=[uid, token]))
    assert resp.status_code == 302 and resp['Location'] == reverse('resetPassword')
    assert client.session['uid'] == str(user_a.pk)


def test_change_password_rejects_weak_password(client, user_a):
    client.force_login(user_a)
    resp = client.post(reverse('change_password'), {
        'current_password': STRONG, 'new_password': 'a', 'confirm_password': 'a'})
    assert resp.status_code == 302
    user_a.refresh_from_db()
    assert user_a.check_password(STRONG)


def test_change_password_accepts_strong_password(client, user_a):
    client.force_login(user_a)
    client.post(reverse('change_password'), {
        'current_password': STRONG, 'new_password': NEW_STRONG, 'confirm_password': NEW_STRONG})
    user_a.refresh_from_db()
    assert user_a.check_password(NEW_STRONG)


# ---- S7: forgot-password must not reveal which emails are registered ----
def test_forgot_password_same_response_for_known_and_unknown_email(user_a):
    known = Client().post(reverse('forgotPassword'), {'email': 'a@example.com'})
    assert len(mail.outbox) == 1  # the real account got its mail
    unknown = Client().post(reverse('forgotPassword'), {'email': 'nobody@example.com'})
    assert len(mail.outbox) == 1  # nothing sent for an unknown address
    assert known.status_code == unknown.status_code == 302
    assert known['Location'] == unknown['Location']
    assert _flash(known) == _flash(unknown)


# ---- B7: an SMTP failure must not turn into a 500 (or into a different response) ----
def test_forgot_password_smtp_failure_looks_the_same(user_a, monkeypatch):
    ok = Client().post(reverse('forgotPassword'), {'email': 'nobody@example.com'})
    monkeypatch.setattr(EmailMessage, 'send', _boom)
    failed = Client().post(reverse('forgotPassword'), {'email': 'a@example.com'})
    assert failed.status_code == 302
    assert failed['Location'] == ok['Location']
    assert _flash(failed) == _flash(ok)


def test_register_email_failure_rolls_back_the_account(client, db, monkeypatch):
    monkeypatch.setattr(EmailMessage, 'send', _boom)
    resp = client.post(reverse('register'), REGISTER)
    assert resp.status_code == 200
    assert not Account.objects.filter(email='new@example.com').exists()
    assert b'verification email' in resp.content


# ---- B3: reset without a valid reset session goes back to login ----
def test_reset_password_without_session_uid_redirects_to_login(client, db):
    resp = client.post(reverse('resetPassword'),
                       {'password': STRONG, 'confirm_password': STRONG})
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
    assert client.get(reverse('resetPassword')).status_code == 302


def test_reset_password_with_stale_uid_redirects_to_login(client, db):
    session = client.session
    session['uid'] = '99999'
    session.save()
    resp = client.post(reverse('resetPassword'),
                       {'password': STRONG, 'confirm_password': STRONG})
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
