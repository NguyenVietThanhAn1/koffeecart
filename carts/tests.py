import re
from decimal import Decimal

from django.test import Client
from django.urls import reverse

from carts.models import Cart, CartItem
from carts.pricing import calculate_totals
from store.models import Variation


def _anon_add(client, product, **variations):
    return client.post(reverse('add_cart', args=[product.id]), variations)


# ---- S5: cart changes must be POST-only (a GET link can be triggered by any site) ----
def test_add_cart_get_not_allowed(client, product):
    assert client.get(reverse('add_cart', args=[product.id])).status_code == 405
    assert CartItem.objects.count() == 0


def test_add_cart_post_adds_and_increments(client, product):
    resp = _anon_add(client, product)
    assert resp.status_code == 302 and resp['Location'] == reverse('cart')
    _anon_add(client, product)
    item = CartItem.objects.get()
    assert item.quantity == 2


def test_remove_cart_and_remove_item_reject_get(client, product):
    _anon_add(client, product)
    _anon_add(client, product)
    item = CartItem.objects.get()
    assert client.get(reverse('remove_cart', args=[product.id, item.id])).status_code == 405
    assert client.get(reverse('remove_cart_item', args=[product.id, item.id])).status_code == 405
    item.refresh_from_db()
    assert item.quantity == 2


def test_remove_cart_post_decrements_then_deletes(client, product):
    _anon_add(client, product)
    _anon_add(client, product)
    item = CartItem.objects.get()
    url = reverse('remove_cart', args=[product.id, item.id])
    assert client.post(url).status_code == 302
    item.refresh_from_db()
    assert item.quantity == 1
    client.post(url)
    assert CartItem.objects.count() == 0


def test_remove_cart_item_post_deletes_line(client, product):
    _anon_add(client, product)
    _anon_add(client, product)
    item = CartItem.objects.get()
    assert client.post(reverse('remove_cart_item', args=[product.id, item.id])).status_code == 302
    assert CartItem.objects.count() == 0


def test_cart_page_actions_are_post_forms(client, product):
    _anon_add(client, product)
    html = client.get(reverse('cart')).content.decode()
    assert 'href="/cart/add_cart/' not in html
    assert 'href="/cart/remove_cart/' not in html
    assert 'href="/cart/remove_cart_item/' not in html
    item = CartItem.objects.get()
    for prefix in ('cart-inc-', 'cart-dec-', 'cart-del-'):
        assert f'id="{prefix}{item.id}"' in html
        assert f'form="{prefix}{item.id}"' in html


def test_cart_plus_form_carries_variation_and_increments_same_line(client, product):
    Variation.objects.create(product=product, variation_category='color', variation_value='red')
    _anon_add(client, product, color='Red')
    html = client.get(reverse('cart')).content.decode()
    assert 'name="color"' in html
    # posting the same variation again must bump the same line, not create a new one
    _anon_add(client, product, color='red')
    item = CartItem.objects.get()
    assert item.quantity == 2


def _form_action_and_token(html, form_id):
    match = re.search(
        r'<form id="%s" action="([^"]+)" method="POST" hidden>\s*'
        r'<input type="hidden" name="csrfmiddlewaretoken" value="([^"]+)"' % form_id, html)
    assert match, f'form {form_id} not found on the cart page'
    return match.group(1), match.group(2)


def test_cart_buttons_work_end_to_end_with_csrf_enforced(product):
    """Like a browser: read the forms and tokens from the page, then submit them."""
    client = Client(enforce_csrf_checks=True)
    page = client.get(product.get_url()).content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    add_url = reverse('add_cart', args=[product.id])

    assert client.post(add_url).status_code == 403  # no token: CSRF protection is active
    assert client.post(add_url, {'csrfmiddlewaretoken': token}).status_code == 302
    item = CartItem.objects.get()

    def submit(prefix):
        html = client.get(reverse('cart')).content.decode()
        action, token = _form_action_and_token(html, f'{prefix}-{item.id}')
        return client.post(action, {'csrfmiddlewaretoken': token})

    assert submit('cart-inc').status_code == 302
    item.refresh_from_db()
    assert item.quantity == 2
    assert submit('cart-dec').status_code == 302
    item.refresh_from_db()
    assert item.quantity == 1
    assert submit('cart-del').status_code == 302
    assert CartItem.objects.count() == 0


# ---- B1 / B11: bad ids and stale items must not crash or be swallowed silently ----
def test_add_cart_unknown_product_404(client, db):
    assert client.post(reverse('add_cart', args=[9999])).status_code == 404


def test_add_cart_unknown_product_404_when_logged_in(client, user_a):
    client.force_login(user_a)
    assert client.post(reverse('add_cart', args=[9999])).status_code == 404


def test_remove_missing_item_is_a_noop_redirect(client, product):
    _anon_add(client, product)
    for name in ('remove_cart', 'remove_cart_item'):
        resp = client.post(reverse(name, args=[product.id, 99999]))
        assert resp.status_code == 302 and resp['Location'] == reverse('cart')
    assert CartItem.objects.count() == 1


def test_cannot_remove_another_users_cart_item(client, user_a, user_b, product):
    item = CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_b)
    for name in ('remove_cart', 'remove_cart_item'):
        assert client.post(reverse(name, args=[product.id, item.id])).status_code == 302
    assert CartItem.objects.filter(id=item.id).exists()


def test_duplicate_variation_rows_do_not_crash_add_cart(client, product):
    Variation.objects.create(product=product, variation_category='color', variation_value='red')
    Variation.objects.create(product=product, variation_category='color', variation_value='red')
    assert _anon_add(client, product, color='red').status_code == 302


def test_guest_cart_merges_into_user_on_login(client, user_a, product):
    _anon_add(client, product)
    resp = client.post(reverse('login'), {'email': 'a@example.com', 'password': 'S3cure-pass-123'})
    assert resp.status_code == 302
    assert CartItem.objects.get().user == user_a


# ---- B10: the cart counter must skip the real admin path only ----
def test_cart_counter_skipped_on_admin_path(client, db):
    resp = client.get('/securelogin/login/')
    assert resp.status_code == 200
    assert 'cart_count' not in resp.context


def test_cart_counter_present_on_page_whose_slug_contains_admin(client, make_product):
    product = make_product(slug='admin-mug')
    resp = client.get(product.get_url())
    assert resp.status_code == 200
    assert resp.context['cart_count'] == 0


# ---- B8: money is Decimal and totals come from one shared function ----
def test_calculate_totals_rounds_tax_half_up(make_product):
    p = make_product(price='19.99')
    item = CartItem(product=p, quantity=3)
    total, quantity, tax, grand_total = calculate_totals([item])
    assert (total, quantity, tax, grand_total) == (
        Decimal('59.97'), 3, Decimal('1.20'), Decimal('61.17'))
    assert all(isinstance(v, Decimal) for v in (total, tax, grand_total))


def test_calculate_totals_empty():
    assert calculate_totals([]) == (Decimal('0.00'), 0, Decimal('0.00'), Decimal('0.00'))


def test_cart_page_shows_exact_totals(client, make_product):
    p = make_product(price='19.99')
    for _ in range(3):
        _anon_add(client, p)
    resp = client.get(reverse('cart'))
    assert resp.context['total'] == Decimal('59.97')
    assert resp.context['tax'] == Decimal('1.20')
    assert resp.context['grand_total'] == Decimal('61.17')


def test_checkout_page_uses_same_totals(client, user_a, make_product):
    p = make_product(price='19.99')
    CartItem.objects.create(user=user_a, product=p, quantity=3)
    client.force_login(user_a)
    resp = client.get(reverse('checkout'))
    assert resp.context['grand_total'] == Decimal('61.17')


def test_cart_count_sums_quantities(client, product):
    _anon_add(client, product)
    _anon_add(client, product)
    assert client.get(reverse('cart')).context['cart_count'] == 2
    assert Cart.objects.count() == 1


# ---- variations: same variation bumps the line, another variation makes a new line ----
def _lines(**filters):
    return {
        tuple(sorted(v.variation_value for v in item.variations.all())): item.quantity
        for item in CartItem.objects.filter(**filters)
    }


def test_guest_variations_split_and_merge_lines(client, product):
    for value in ('red', 'blue'):
        Variation.objects.create(product=product, variation_category='color', variation_value=value)
    _anon_add(client, product, color='red')
    _anon_add(client, product, color='red')
    _anon_add(client, product, color='blue')
    _anon_add(client, product)  # no variation: yet another line
    assert _lines() == {('red',): 2, ('blue',): 1, (): 1}


def test_logged_in_variations_split_and_merge_lines(client, user_a, product):
    for value in ('red', 'blue'):
        Variation.objects.create(product=product, variation_category='color', variation_value=value)
    client.force_login(user_a)
    for color in ('red', 'red', 'blue'):
        client.post(reverse('add_cart', args=[product.id]), {'color': color})
    assert _lines(user=user_a) == {('red',): 2, ('blue',): 1}


def test_logged_in_remove_cart_decrements(client, user_a, product):
    item = CartItem.objects.create(user=user_a, product=product, quantity=2)
    client.force_login(user_a)
    client.post(reverse('remove_cart', args=[product.id, item.id]))
    item.refresh_from_db()
    assert item.quantity == 1


# ---- R6: logging in merges the guest cart into the user's cart, line by line ----
def _login(client):
    return client.post(reverse('login'), {'email': 'a@example.com', 'password': 'S3cure-pass-123'})


def test_login_merge_adds_quantities_of_same_line(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    _anon_add(client, product)
    _anon_add(client, product)  # the guest has 2
    _login(client)
    line = CartItem.objects.get(product=product)  # exactly one line left
    assert line.user == user_a and line.quantity == 3


def test_login_merge_keeps_different_variations_apart(client, user_a, product):
    red = Variation.objects.create(product=product, variation_category='color', variation_value='red')
    Variation.objects.create(product=product, variation_category='color', variation_value='blue')
    mine = CartItem.objects.create(user=user_a, product=product, quantity=1)
    mine.variations.add(red)
    _anon_add(client, product, color='blue')
    _anon_add(client, product, color='red')
    _login(client)
    assert _lines(user=user_a) == {('red',): 2, ('blue',): 1}
    assert not CartItem.objects.filter(user__isnull=True).exists()  # no orphaned guest lines


# ---- R7: the very first request of a new visitor already has a cart id ----
def test_cart_id_is_set_on_first_request(rf):
    from django.contrib.sessions.middleware import SessionMiddleware
    from carts.views import _cart_id
    request = rf.get('/')
    SessionMiddleware(lambda r: None).process_request(request)
    assert request.session.session_key is None
    assert _cart_id(request) is None  # only looking: no session is created (V1)
    cart_id = _cart_id(request, create=True)
    assert cart_id and cart_id == request.session.session_key
