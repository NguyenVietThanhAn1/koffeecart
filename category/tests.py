from django.urls import reverse

from category.models import Category
from store.models import Product


def test_category_url_and_str(db):
    cat = Category.objects.create(category_name='Beans', slug='beans')
    assert cat.get_url() == reverse('products_by_category', args=['beans'])
    assert str(cat) == 'Beans'


def test_menu_links_available_on_every_page(client, db):
    Category.objects.create(category_name='Beans', slug='beans')
    Category.objects.create(category_name='Gear', slug='gear')
    resp = client.get(reverse('home'))
    assert sorted(c.slug for c in resp.context['links']) == ['beans', 'gear']


def test_products_by_category_lists_only_that_category(client, make_product):
    in_beans = make_product()
    gear = Category.objects.create(category_name='Gear', slug='gear')
    Product.objects.create(product_name='Grinder', slug='grinder', price=5, stock=1,
                           category=gear, images='photos/products/x.jpg')
    resp = client.get(reverse('products_by_category', args=['beans']))
    assert resp.status_code == 200
    assert [p.product_name for p in resp.context['products']] == [in_beans.product_name]


def test_unknown_category_is_404(client, db):
    assert client.get(reverse('products_by_category', args=['nope'])).status_code == 404
