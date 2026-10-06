"""Phase 5: the new Bootstrap 5 templates, security headers and error pages."""
import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from carts.models import CartItem
from store.models import Variation
from store.templatetags.store_extras import star_icons

FULL, HALF, EMPTY = 'fas fa-star', 'fas fa-star-half-alt', 'far fa-star'


# ---- pages render with the new assets, and nothing the CSP would block ----
@pytest.fixture
def pages(client, user_a, product, make_order):
    """Every main page as the logged-in user sees it, with a cart and one placed order."""
    order = make_order(user_a)
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    urls = [
        reverse('home'), reverse('store'), product.get_url(), reverse('search') + '?keyword=a',
        reverse('cart'), reverse('checkout'), reverse('dashboard'), reverse('my_orders'),
        reverse('edit_profile'), reverse('change_password'),
        reverse('order_detail', args=[order.order_number]),
    ]
    return {url: client.get(url) for url in urls}


def test_main_pages_render(pages):
    for url, resp in pages.items():
        assert resp.status_code == 200, url


def test_pages_load_bootstrap5_and_no_old_assets(pages):
    for url, resp in pages.items():
        html = resp.content.decode()
        assert 'vendor/bootstrap-5.3.8/bootstrap.min.css' in html, url
        for old in ('jquery', 'paypal.com', 'css/ui.css', 'font-awesome/4.7.0', 'data-toggle='):
            assert old not in html.lower(), (url, old)


def test_pages_have_no_inline_scripts_or_styles(pages):
    """style-src/script-src 'self' would block these in the browser."""
    for url, resp in pages.items():
        html = resp.content.decode()
        assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html), url
        assert ' style="' not in html, url
        assert '<style' not in html, url
        assert not re.search(r'\son[a-z]+="', html), url  # onclick=, onload=...


def test_csp_header_on_shop_pages(client, db):
    csp = client.get(reverse('home'))['Content-Security-Policy']
    assert "script-src 'self'" in csp and "style-src 'self';" in csp
    assert "frame-ancestors 'none'" in csp
    assert 'unsafe-inline' not in csp


def test_admin_csp_allows_inline_styles_only(client, db):
    csp = client.get(reverse('admin:login'))['Content-Security-Policy']
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self';" in csp


def test_permissions_policy_header(client, db):
    assert 'camera=()' in client.get(reverse('home'))['Permissions-Policy']


# ---- logout is a POST (a GET link could be triggered by any other site) ----
def test_logout_rejects_get(client, user_a):
    client.force_login(user_a)
    assert client.get(reverse('logout')).status_code == 405
    assert client.get(reverse('dashboard')).status_code == 200  # still logged in


def test_navbar_logout_is_a_post_form(client, user_a):
    client.force_login(user_a)
    html = client.get(reverse('home')).content.decode()
    assert re.search(r'<form action="%s" method="POST">' % reverse('logout'), html)
    assert f'href="{reverse("logout")}"' not in html


# ---- cart page: totals and a checkout button, no billing form any more ----
def test_cart_page_shows_totals_and_checkout_link(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=2)
    client.force_login(user_a)
    html = client.get(reverse('cart')).content.decode()
    assert '$200.00' in html and '$4.00' in html and '$204.00' in html
    assert f'href="{reverse("checkout")}"' in html
    assert f'action="{reverse("place_order")}"' not in html


def test_empty_cart_page(client, db):
    html = client.get(reverse('cart')).content.decode()
    assert 'Your cart is empty' in html


def test_checkout_prefills_user_details(client, user_a, product):
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    html = client.get(reverse('checkout')).content.decode()
    assert 'value="a@example.com"' in html
    assert f'action="{reverse("place_order")}"' in html


# ---- product page: variations can be chosen ----
def test_product_page_offers_variations(client, product):
    for colour in ('red', 'blue'):
        Variation.objects.create(product=product, variation_category='color', variation_value=colour)
    html = client.get(product.get_url()).content.decode()
    assert '<select id="variation-color" name="color"' in html
    assert 'value="blue"' in html and 'value="red"' in html


def test_review_form_only_for_buyers(client, user_a, product, buy):
    client.force_login(user_a)
    assert 'Only customers who bought' in client.get(product.get_url()).content.decode()
    buy(user_a, product)
    assert 'name="rating"' in client.get(product.get_url()).content.decode()


# ---- stars ----
@pytest.mark.parametrize('value, expected', [
    (0, [EMPTY] * 5),
    (None, [EMPTY] * 5),
    (0.5, [HALF] + [EMPTY] * 4),
    (3.5, [FULL] * 3 + [HALF, EMPTY]),
    (4.2, [FULL] * 4 + [EMPTY]),
    (5, [FULL] * 5),
])
def test_star_icons(value, expected):
    assert star_icons(value) == expected


# ---- error pages ----
def test_custom_404_page(client, db):
    resp = client.get('/no-such-page/')
    assert resp.status_code == 404
    assert b'Page not found' in resp.content


def test_500_page_renders_without_request_context():
    html = render_to_string('500.html')
    assert 'Something went wrong' in html
    assert 'bootstrap.min.css' in html
