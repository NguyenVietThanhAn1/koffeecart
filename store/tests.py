import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from store.models import Product, ReviewRating


# S4 — submit_review needs login and POST
def test_submit_review_requires_login(client, product):
    resp = client.post(reverse('submit_review', args=[product.id]),
                       {'subject': 's', 'review': 'r', 'rating': 5})
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_submit_review_rejects_get(client, user_a, product):
    client.force_login(user_a)
    assert client.get(reverse('submit_review', args=[product.id])).status_code == 405


# ---- B5: validate before saving; Referer may be missing or external ----
GOOD_REVIEW = {'subject': 'Great', 'review': 'Tastes nice', 'rating': '4.5'}


@pytest.fixture
def buyer(user_a, product, buy):
    """user_a, who has bought `product` and so may review it."""
    buy(user_a, product)
    return user_a


def _review(client, product, referer=None, **data):
    extra = {'HTTP_REFERER': referer} if referer is not None else {}
    return client.post(reverse('submit_review', args=[product.id]), data, **extra)


def test_submit_review_creates_then_updates(client, buyer, product):
    client.force_login(buyer)
    back = 'http://testserver' + product.get_url()
    resp = _review(client, product, referer=back, **GOOD_REVIEW)
    assert resp.status_code == 302 and resp['Location'] == back
    resp = _review(client, product, referer=back, **dict(GOOD_REVIEW, subject='Edited'))
    assert resp.status_code == 302
    review = ReviewRating.objects.get()  # still exactly one review
    assert review.subject == 'Edited' and review.user == buyer


def test_submit_review_invalid_new_review_does_not_crash(client, buyer, product):
    client.force_login(buyer)
    resp = _review(client, product, **dict(GOOD_REVIEW, rating='abc'))
    assert resp.status_code == 302
    assert ReviewRating.objects.count() == 0


def test_submit_review_invalid_update_keeps_old_review(client, buyer, product):
    client.force_login(buyer)
    _review(client, product, **GOOD_REVIEW)
    resp = _review(client, product, **dict(GOOD_REVIEW, subject='Bad', rating='abc'))
    assert resp.status_code == 302
    assert ReviewRating.objects.get().subject == 'Great'


def test_submit_review_without_referer_goes_to_product_page(client, buyer, product):
    client.force_login(buyer)
    resp = _review(client, product, **GOOD_REVIEW)
    assert resp.status_code == 302
    assert resp['Location'] == product.get_url()


def test_submit_review_ignores_external_referer(client, buyer, product):
    client.force_login(buyer)
    resp = _review(client, product, referer='https://evil.com/x', **GOOD_REVIEW)
    assert resp.status_code == 302
    assert resp['Location'] == product.get_url()


def test_submit_review_unknown_product_404(client, user_a, db):
    client.force_login(user_a)
    resp = client.post(reverse('submit_review', args=[9999]), GOOD_REVIEW)
    assert resp.status_code == 404


# ---- B1 (same class): an unknown product page is a 404, not a 500 ----
def test_product_detail_unknown_slug_404(client, product):
    assert client.get('/store/category/beans/no-such-product/').status_code == 404


def test_product_detail_ok(client, product):
    assert client.get(product.get_url()).status_code == 200


# ---- B9: list pages must not run extra queries per product ----
def _queries(client, url):
    # Warm up: the first requests create the session and the session-timeout middleware
    # rewrites it once; after that a request costs a fixed number of queries.
    client.get(url)
    client.get(url)
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(url).status_code == 200
    return len(ctx)


def _add_products(make_product, user, n):
    for _ in range(n):
        p = make_product()
        ReviewRating.objects.create(product=p, user=user, rating=4, subject='ok')


def test_home_query_count_does_not_grow_with_products(client, user_a, make_product):
    _add_products(make_product, user_a, 2)
    few = _queries(client, reverse('home'))
    _add_products(make_product, user_a, 5)
    many = _queries(client, reverse('home'))
    assert many == few


def test_store_query_count_does_not_grow_with_products(client, user_a, make_product):
    _add_products(make_product, user_a, 2)
    few = _queries(client, reverse('store'))
    _add_products(make_product, user_a, 1)  # store paginates by 3, so stay within one page
    many = _queries(client, reverse('store'))
    assert many == few


def test_search_query_count_does_not_grow_with_products(client, user_a, make_product):
    url = reverse('search') + '?keyword=Product'
    _add_products(make_product, user_a, 2)
    few = _queries(client, url)
    _add_products(make_product, user_a, 5)
    many = _queries(client, url)
    assert many == few


def test_home_shows_correct_average_and_count_per_product(client, user_a, user_b, make_product):
    rated = make_product()
    unrated = make_product()
    hidden = make_product()
    ReviewRating.objects.create(product=rated, user=user_a, rating=5)
    ReviewRating.objects.create(product=rated, user=user_b, rating=3)
    ReviewRating.objects.create(product=hidden, user=user_a, rating=1, status=False)
    resp = client.get(reverse('home'))
    by_id = {p.id: p for p in resp.context['products']}
    assert by_id[rated.id].averageReview() == 4.0
    assert by_id[rated.id].countReview() == 2
    assert by_id[unrated.id].averageReview() == 0
    assert by_id[unrated.id].countReview() == 0
    assert by_id[hidden.id].countReview() == 0  # unpublished reviews are not counted


def test_ratings_still_work_on_a_plain_product(user_a, product):
    ReviewRating.objects.create(product=product, user=user_a, rating=2)
    plain = Product.objects.get(id=product.id)  # not annotated
    assert plain.averageReview() == 2.0
    assert plain.countReview() == 1


# ---- R3: only buyers can review, and the rating must be within 0.5-5 ----
def test_review_from_non_buyer_is_rejected(client, user_b, product):
    client.force_login(user_b)
    resp = _review(client, product, **GOOD_REVIEW)
    assert resp.status_code == 302
    assert ReviewRating.objects.count() == 0


@pytest.mark.parametrize('rating', ['9', '0', '-5'])
def test_review_rating_out_of_range_is_rejected(client, buyer, product, rating):
    client.force_login(buyer)
    _review(client, product, **dict(GOOD_REVIEW, rating=rating))
    assert ReviewRating.objects.count() == 0


# ---- R8: a category page lists more than one product per page ----
def test_category_page_shows_several_products(client, make_product):
    made = [make_product() for _ in range(3)]
    resp = client.get(reverse('products_by_category', args=[made[0].category.slug]))
    assert len(resp.context['products']) == 3


# ---- R9: the product page knows the item is in a logged-in user's cart ----
def test_product_detail_in_cart_for_logged_in_user(client, user_a, product):
    from carts.models import CartItem
    CartItem.objects.create(user=user_a, product=product, quantity=1)
    client.force_login(user_a)
    assert client.get(product.get_url()).context['in_cart'] is True


# ---- R10: search must not show products that are hidden from the shop ----
def test_search_hides_unavailable_products(client, make_product):
    hidden = make_product()
    hidden.is_available = False
    hidden.save()
    resp = client.get(reverse('search'), {'keyword': hidden.product_name})
    assert resp.context['product_count'] == 0
