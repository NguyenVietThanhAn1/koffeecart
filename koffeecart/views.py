from django.db.models import Count, F, OuterRef, Q, Subquery
from django.shortcuts import render

from category.models import Category
from store.models import Product

SECTION_SIZE = 6     # one row of cards in the deals / best seller strips
GRID_SIZE = 18       # "Recommended for you" grid


def home(request):
    listing = Product.objects.filter(is_available=True).for_listing()

    # Biggest discount first: (was - now) / was
    deals = list(listing.filter(compare_at_price__gt=F('price'))
                 .order_by(((F('compare_at_price') - F('price')) / F('compare_at_price')).desc(), 'id')
                 [:SECTION_SIZE])
    best_sellers = listing.filter(sold__gt=0).order_by('-sold', 'id')

    # Category tiles: the category's own image if it has one, else its first product's photo.
    first_photo = (Product.objects.filter(category=OuterRef('pk'), is_available=True)
                   .order_by('id').values('images')[:1])
    categories = (Category.objects
                  .annotate(cover=Subquery(first_photo),
                            product_count=Count('product', filter=Q(product__is_available=True)))
                  .filter(product_count__gt=0)
                  .order_by('category_name'))

    return render(request, 'home.html', {
        'deals': deals,
        'best_sellers': best_sellers[:SECTION_SIZE],
        'categories': categories,
        'products': listing.order_by('-created_date', 'id')[:GRID_SIZE],
        'max_discount': max((p.discount_percent for p in deals), default=0),
    })
