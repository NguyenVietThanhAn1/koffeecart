from django.shortcuts import render
from store.models import Product


def home(request):
    products = (
        Product.objects.filter(is_available=True)
        .select_related('category')  # product.get_url needs the category slug
        .with_ratings()              # stars: one query for all products, not two per product
        .order_by('created_date')
    )
    return render(request, 'home.html', {'products': products})
