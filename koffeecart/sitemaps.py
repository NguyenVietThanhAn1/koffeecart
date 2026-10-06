from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from category.models import Category
from store.models import Product


class StaticSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return ['home', 'store']

    def location(self, name):
        return reverse(name)


class CategorySitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.order_by('slug')

    def location(self, category):
        return category.get_url()


class ProductSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        # hidden products answer 404, so they must not be advertised to search engines
        return Product.objects.filter(is_available=True).select_related('category').order_by('id')

    def location(self, product):
        return product.get_url()

    def lastmod(self, product):
        return product.modified_date


SITEMAPS = {'static': StaticSitemap, 'categories': CategorySitemap, 'products': ProductSitemap}
