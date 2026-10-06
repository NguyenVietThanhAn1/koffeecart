"""Shop features of the Amazon/Shopee-style UI: sale prices, sold counts, filters, sorting,
buy now, quantities, home sections, rating breakdown."""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import Account
from carts.models import CartItem
from orders.models import OrderProduct
from store.models import Product, ReviewRating
from store.templatetags.store_extras import compact, kc_width
from store.views import _rating_breakdown

STRONG = 'S3cure-pass-123'


def _user(n):
    return Account.objects.create_user(first_name='U', last_name=str(n), username=f'u{n}',
                                       email=f'u{n}@example.com', password=STRONG)


def _sell(product, user, quantity, make_order, number):
    order = make_order(user, number=number, paid=True)
    OrderProduct.objects.create(order=order, payment=order.payment, user=user, product=product,
                                quantity=quantity, product_price=product.price, ordered=True)


# ---- sale price ----
def test_discount_percent(make_product):
    p = make_product(price='12.50')
    assert p.discount_percent == 0
    p.compare_at_price = Decimal('15.00')
    assert p.discount_percent == 17  # 16.67 rounded half up


def test_compare_price_must_be_above_price(make_product):
    p = make_product(price='10.00')
    p.compare_at_price = Decimal('9.00')
    with pytest.raises(ValidationError):
        p.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        p.save()  # the database refuses it too (check constraint)


# ---- sold count: a subquery, so reviews do not multiply it ----
def test_sold_count_is_not_inflated_by_reviews(make_product, make_order):
    p = make_product()
    buyers = [_user(i) for i in range(3)]
    for i, buyer in enumerate(buyers):
        _sell(p, buyer, quantity=2, make_order=make_order, number=f'S{i}')
        ReviewRating.objects.create(product=p, user=buyer, rating=4 + (i % 2))
    listed = Product.objects.for_listing().get(pk=p.pk)
    assert listed.sold == 6
    assert listed.review_count == 3
    assert listed.averageReview() == pytest.approx(13 / 3)


def test_unplaced_order_lines_are_not_sold(make_product, user_a, make_order):
    p = make_product()
    order = make_order(user_a, number='U1', paid=False)
    OrderProduct.objects.create(order=order, user=user_a, product=p, quantity=5,
                                product_price=p.price, ordered=False)
    assert Product.objects.for_listing().get(pk=p.pk).sold == 0


# ---- filters and sorting ----
@pytest.fixture
def shelf(make_product, make_order):
    cheap = make_product(price='5.00', stock=0)
    mid = make_product(price='12.00')
    mid.compare_at_price = Decimal('15.00')
    mid.save()
    dear = make_product(price='30.00')
    buyer = _user(99)
    _sell(dear, buyer, 7, make_order, 'B1')
    ReviewRating.objects.create(product=mid, user=buyer, rating=5)
    ReviewRating.objects.create(product=cheap, user=buyer, rating=2)
    return {'cheap': cheap, 'mid': mid, 'dear': dear}


def _names(client, **params):
    resp = client.get(reverse('store'), params)
    assert resp.status_code == 200
    return [p.product_name for p in resp.context['products']]


def test_price_range_filter(client, shelf):
    assert _names(client, min_price='10', max_price='20') == [shelf['mid'].product_name]


def test_rating_filter(client, shelf):
    assert _names(client, rating='4') == [shelf['mid'].product_name]


def test_in_stock_and_on_sale_filters(client, shelf):
    assert shelf['cheap'].product_name not in _names(client, in_stock='1')
    assert _names(client, on_sale='1') == [shelf['mid'].product_name]


@pytest.mark.parametrize('sort, first', [
    ('price_asc', 'cheap'), ('price_desc', 'dear'), ('sales', 'dear'), ('rating', 'mid'), ('popular', 'dear'),
])
def test_sorting(client, shelf, sort, first):
    assert _names(client, sort=sort)[0] == shelf[first].product_name


@pytest.mark.parametrize('params', [
    {'sort': 'drop table'}, {'min_price': 'abc'}, {'rating': '9'}, {'page': 'x'},
])
def test_bad_filter_values_are_ignored(client, shelf, params):
    assert len(_names(client, **params)) == 3


def test_pagination_keeps_the_filters(client, make_product):
    for _ in range(14):
        make_product(price='9.00')
    html = client.get(reverse('store'), {'sort': 'price_asc', 'max_price': '10'}).content.decode()
    assert 'href="?sort=price_asc&amp;max_price=10&amp;page=2"' in html


def test_search_within_a_category(client, make_product):
    from category.models import Category
    other = Category.objects.create(category_name='Gear', slug='gear')
    bean = make_product()
    mug = make_product()
    mug.category = other
    mug.save()
    resp = client.get(reverse('search'), {'keyword': 'Product', 'category': 'gear'})
    assert [p.pk for p in resp.context['products']] == [mug.pk]
    assert bean.pk not in [p.pk for p in resp.context['products']]


def test_empty_search_goes_to_the_store(client, make_product):
    make_product()
    resp = client.get(reverse('search'), {'keyword': ''})
    assert resp.status_code == 302 and resp['Location'] == reverse('store')


def test_empty_search_in_a_category_goes_to_that_category(client, make_product):
    p = make_product()
    resp = client.get(reverse('search'), {'keyword': '', 'category': p.category.slug})
    assert resp['Location'] == p.category.get_url()


def test_checkout_prefills_the_saved_address(client, user_a, product):
    from accounts.models import UserProfile
    UserProfile.objects.create(user=user_a, address_line_1='12 Bean Lane', city='Da Lat',
                               state='Lam Dong', country='Vietnam')
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    html = client.get(reverse('checkout')).content.decode()
    for value in ('12 Bean Lane', 'Da Lat', 'Lam Dong', 'Vietnam'):
        assert f'value="{value}"' in html


def test_admin_edits_price_and_stock_from_the_product_list(client, product):
    admin = Account.objects.create_superuser(first_name='A', last_name='D', email='ad@example.com',
                                             username='ad', password=STRONG)
    client.force_login(admin)
    data = {
        'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '0',
        'form-MAX_NUM_FORMS': '1000', 'form-0-id': str(product.pk), 'form-0-price': '90.00',
        'form-0-compare_at_price': '100.00', 'form-0-stock': '7', 'form-0-is_available': 'on',
        '_save': 'Save',
    }
    assert client.post(reverse('admin:store_product_changelist'), data).status_code == 302
    product.refresh_from_db()
    assert (product.price, product.compare_at_price, product.stock) == (Decimal('90.00'), Decimal('100.00'), 7)
    # a "was" price below the price is refused by the form (and by the database)
    data['form-0-compare_at_price'] = '50.00'
    assert client.post(reverse('admin:store_product_changelist'), data).status_code == 200
    product.refresh_from_db()
    assert product.compare_at_price == Decimal('100.00')


# ---- add to cart: quantity and buy now ----
def test_add_quantity(client, product):
    client.post(reverse('add_cart', args=[product.id]), {'quantity': '3'})
    assert CartItem.objects.get().quantity == 3


def test_quantity_is_capped_by_stock(client, product):  # stock is 5
    resp = client.post(reverse('add_cart', args=[product.id]), {'quantity': '50'})
    assert CartItem.objects.get().quantity == 5
    assert resp['Location'] == reverse('cart')


@pytest.mark.parametrize('raw', ['abc', '-4', '0', ''])
def test_bad_quantity_adds_one(client, product, raw):
    client.post(reverse('add_cart', args=[product.id]), {'quantity': raw})
    assert CartItem.objects.get().quantity == 1


def test_buy_now_goes_to_checkout(client, user_a, product):
    client.force_login(user_a)
    resp = client.post(reverse('add_cart', args=[product.id]), {'buy_now': '1'})
    assert resp['Location'] == reverse('checkout')
    assert CartItem.objects.get(user=user_a).quantity == 1


def test_buy_now_as_guest_asks_to_sign_in_first(client, product):
    resp = client.post(reverse('add_cart', args=[product.id]), {'buy_now': '1'}, follow=True)
    assert resp.redirect_chain[-1][0].startswith(reverse('login'))
    assert CartItem.objects.count() == 1  # kept in the guest cart, merged on login


# ---- home page sections ----
def test_home_sections(client, shelf):
    ctx = client.get(reverse('home')).context
    assert [p.pk for p in ctx['deals']] == [shelf['mid'].pk]
    assert ctx['max_discount'] == 20
    assert [p.pk for p in ctx['best_sellers']] == [shelf['dear'].pk]
    assert [c.product_count for c in ctx['categories']] == [3]


# ---- product page ----
def test_rating_breakdown():
    class R:
        def __init__(self, rating):
            self.rating = rating
    rows = _rating_breakdown([R(5), R(4.5), R(4), R(1)])
    assert rows == [(5, 2, 50), (4, 1, 25), (3, 0, 0), (2, 0, 0), (1, 1, 25)]
    assert _rating_breakdown([])[0] == (5, 0, 0)


def test_product_page_shows_sale_and_related(client, shelf):
    html = client.get(shelf['mid'].get_url()).content.decode()
    assert '$15.00' in html and '20% OFF' in html
    resp = client.get(shelf['mid'].get_url())
    related = [p.pk for p in resp.context['related_products']]
    assert shelf['mid'].pk not in related and set(related) == {shelf['cheap'].pk, shelf['dear'].pk}


def test_verified_badge_only_for_buyers(client, shelf, make_order):
    # The 2-star review on "cheap" was written without buying it (allowed before the buyers-only rule).
    html = client.get(shelf['cheap'].get_url()).content.decode()
    assert 'Verified purchase' not in html


def test_quantity_picker_respects_what_is_already_in_the_cart(client, product):
    client.post(reverse('add_cart', args=[product.id]), {'quantity': '4'})
    html = client.get(product.get_url()).content.decode()
    assert 'max="1"' in html  # stock 5, 4 in the cart


# ---- template filters ----
@pytest.mark.parametrize('n, text', [(0, '0'), (999, '999'), (1000, '1k'), (1250, '1.2k'), (25400, '25k')])
def test_compact(n, text):
    assert compact(n) == text


@pytest.mark.parametrize('pct, cls', [(0, 'kc-w-0'), (33, 'kc-w-35'), (67, 'kc-w-65'), (100, 'kc-w-100'), (140, 'kc-w-100')])
def test_kc_width(pct, cls):
    assert kc_width(pct) == cls
