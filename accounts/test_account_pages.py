"""Everyday account flows: activation, login/logout, dashboard, profile, passwords."""
import pytest
from django.contrib.auth.tokens import default_token_generator
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Account, UserProfile

STRONG = 'S3cure-pass-123'


def _flash(resp):
    return [str(m) for m in get_messages(resp.wsgi_request)]


@pytest.fixture
def inactive_user(db):
    return Account.objects.create_user(
        first_name='In', last_name='Active', username='inactive',
        email='inactive@example.com', password=STRONG)


def _activation_url(user, token=None):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return reverse('activate', args=[uid, token or default_token_generator.make_token(user)])


# ---- activation ----
def test_activation_link_activates_the_account(client, inactive_user):
    resp = client.get(_activation_url(inactive_user))
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
    inactive_user.refresh_from_db()
    assert inactive_user.is_active is True


def test_activation_with_wrong_token_is_rejected(client, inactive_user):
    resp = client.get(_activation_url(inactive_user, token='bad-token'))
    assert resp.status_code == 302 and resp['Location'] == reverse('register')
    inactive_user.refresh_from_db()
    assert inactive_user.is_active is False


def test_activation_with_garbage_uid_is_rejected(client, db):
    resp = client.get(reverse('activate', args=['zzz', 'bad-token']))
    assert resp.status_code == 302 and resp['Location'] == reverse('register')


# ---- login / logout ----
def test_login_with_wrong_password_is_refused(client, user_a):
    resp = client.post(reverse('login'), {'email': 'a@example.com', 'password': 'wrong'})
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
    assert 'Invalid login credentials' in _flash(resp)


def test_inactive_account_cannot_log_in(client, inactive_user):
    resp = client.post(reverse('login'), {'email': 'inactive@example.com', 'password': STRONG})
    assert resp.status_code == 302 and resp['Location'] == reverse('login')


def test_login_page_renders(client, db):
    assert client.get(reverse('login')).status_code == 200


def test_logout_ends_the_session(client, user_a):
    client.force_login(user_a)
    assert client.get(reverse('logout')).status_code == 302
    resp = client.get(reverse('dashboard'))
    assert resp.status_code == 302 and resp['Location'].startswith(reverse('login'))


# ---- dashboard and orders ----
def test_dashboard_counts_only_placed_orders(client, user_a, make_order):
    make_order(user_a, number='202601011')
    make_order(user_a, number='202601012', paid=False)
    client.force_login(user_a)
    resp = client.get(reverse('dashboard'))
    assert resp.status_code == 200
    assert resp.context['orders_count'] == 1
    assert UserProfile.objects.filter(user=user_a).exists()


def test_my_orders_lists_only_own_placed_orders(client, user_a, user_b, make_order):
    make_order(user_a, number='202601011')
    make_order(user_a, number='202601012', paid=False)
    make_order(user_b, number='202601013')
    client.force_login(user_a)
    html = client.get(reverse('my_orders')).content.decode()
    assert '202601011' in html
    assert '202601012' not in html and '202601013' not in html


# ---- profile ----
PROFILE = {
    'first_name': 'Newname', 'last_name': 'Lastname', 'phone_number': '0911111111',
    'address_line_1': '1 Main St', 'address_line_2': '', 'city': 'Saigon',
    'state': 'HCM', 'country': 'VN',
}


def test_edit_profile_page_renders(client, user_a):
    client.force_login(user_a)
    assert client.get(reverse('edit_profile')).status_code == 200


def test_edit_profile_saves_changes(client, user_a):
    client.force_login(user_a)
    resp = client.post(reverse('edit_profile'), PROFILE)
    assert resp.status_code == 302
    user_a.refresh_from_db()
    assert user_a.first_name == 'Newname'
    assert UserProfile.objects.get(user=user_a).city == 'Saigon'


def test_edit_profile_rejects_invalid_data(client, user_a):
    client.force_login(user_a)
    resp = client.post(reverse('edit_profile'), dict(PROFILE, first_name='x' * 80))
    assert resp.status_code == 200
    user_a.refresh_from_db()
    assert user_a.first_name == 'Test'


# ---- passwords: the "no" paths ----
def test_change_password_wrong_current_password(client, user_a):
    client.force_login(user_a)
    resp = client.post(reverse('change_password'), {
        'current_password': 'nope', 'new_password': 'An0ther-Str0ng-pass',
        'confirm_password': 'An0ther-Str0ng-pass'})
    assert resp.status_code == 302
    user_a.refresh_from_db()
    assert user_a.check_password(STRONG)


def test_change_password_confirmation_mismatch(client, user_a):
    client.force_login(user_a)
    client.post(reverse('change_password'), {
        'current_password': STRONG, 'new_password': 'An0ther-Str0ng-pass',
        'confirm_password': 'different-One-123'})
    user_a.refresh_from_db()
    assert user_a.check_password(STRONG)


def test_reset_password_confirmation_mismatch(client, user_a):
    session = client.session
    session['uid'] = str(user_a.pk)
    session.save()
    resp = client.post(reverse('resetPassword'), {
        'password': 'An0ther-Str0ng-pass', 'confirm_password': 'different-One-123'})
    assert resp.status_code == 302 and resp['Location'] == reverse('resetPassword')
    user_a.refresh_from_db()
    assert user_a.check_password(STRONG)


def test_reset_password_link_with_bad_token(client, user_a):
    uid = urlsafe_base64_encode(force_bytes(user_a.pk))
    resp = client.get(reverse('resetpassword_validate', args=[uid, 'bad-token']))
    assert resp.status_code == 302 and resp['Location'] == reverse('login')
    assert 'uid' not in client.session


# ---- registration: the "no" paths ----
REGISTER = {
    'first_name': 'New', 'last_name': 'User', 'phone_number': '0900000000',
    'email': 'new@example.com', 'password': STRONG, 'confirm_password': STRONG,
}


def test_register_password_confirmation_mismatch(client, db):
    resp = client.post(reverse('register'), dict(REGISTER, confirm_password='different-One-123'))
    assert resp.status_code == 200
    assert not Account.objects.filter(email='new@example.com').exists()


def test_register_rejects_an_email_that_is_already_used(client, user_a):
    resp = client.post(reverse('register'), dict(REGISTER, email='a@example.com'))
    assert resp.status_code == 200
    assert Account.objects.filter(email='a@example.com').count() == 1


def test_register_page_renders(client, db):
    assert client.get(reverse('register')).status_code == 200
