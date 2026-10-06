from django.shortcuts import render, get_object_or_404, redirect
from .models import Product, ReviewRating, ProductGallery
from category.models import Category
from django.db.models import Q, Sum
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from carts.views import _cart_items
from django.core.paginator import Paginator
from django.utils.http import url_has_allowed_host_and_scheme
from .filters import DEFAULT_SORT, SORTS, ProductFilterForm, apply_filters
from .forms import ReviewForm
from django.contrib import messages
from orders.models import OrderProduct

PRODUCTS_PER_PAGE = 12
RELATED_PRODUCTS = 6


def _listing(request, products, *, category=None, keyword=''):
    """Store, category and search pages: same filters, sorting, pagination and template."""
    form = ProductFilterForm(request.GET)
    values = form.values()
    products = apply_filters(products.for_listing(), values)
    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    return render(request, 'store/store.html', {
        'products': paginator.get_page(request.GET.get('page')),
        'product_count': paginator.count,
        'filters': values,
        'sort': values.get('sort', DEFAULT_SORT),
        'sorts': [(key, label) for key, (label, _) in SORTS.items()],
        'current_category': category,
        'keyword': keyword,
    })


def store(request, category_slug=None):
    products = Product.objects.filter(is_available=True)
    category = None
    if category_slug is not None:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)
    return _listing(request, products, category=category)


def search(request):
    values = ProductFilterForm(request.GET).values()
    keyword = values.get('keyword', '')
    # The header search box can narrow the search to one category.
    category = Category.objects.filter(slug=values['category']).first() if 'category' in values else None
    if not keyword:
        # Nothing typed: show the chosen department, or the whole store (like Amazon).
        return redirect(category.get_url() if category else 'store')
    products = Product.objects.filter(is_available=True).filter(
        Q(description__icontains=keyword) | Q(product_name__icontains=keyword))
    if category is not None:
        products = products.filter(category=category)
    return _listing(request, products, category=category, keyword=keyword)


def _rating_breakdown(reviews):
    """Amazon-style bars: [(stars, count, percent)] from 5 down to 1; half stars round up."""
    counts = {stars: 0 for stars in range(1, 6)}
    for review in reviews:
        counts[min(5, max(1, int(review.rating + 0.5)))] += 1
    total = sum(counts.values())
    return [(stars, counts[stars], round(counts[stars] * 100 / total) if total else 0)
            for stars in range(5, 0, -1)]


def product_detail(request, category_slug, product_slug):
    single_product = get_object_or_404(
        Product.objects.for_listing(), category__slug=category_slug, slug=product_slug, is_available=True)
    # _cart_items() looks at the user's cart when logged in, at the guest cart otherwise.
    cart_item = _cart_items(request).filter(product=single_product).first()
    in_cart = cart_item is not None
    in_cart_quantity = (_cart_items(request).filter(product=single_product)
                        .aggregate(n=Sum('quantity'))['n'] or 0)

    if request.user.is_authenticated:
        orderproduct = OrderProduct.objects.filter(
            user=request.user, product_id=single_product.id, ordered=True).exists()
    else:
        orderproduct = None

    reviews = list(ReviewRating.objects.filter(product_id=single_product.id, status=True)
                   .select_related('user').order_by('-updated_at'))
    # "Verified purchase" only where it is true (reviews written before the buyers-only rule may not be).
    verified_buyers = set(OrderProduct.objects.filter(
        product=single_product, ordered=True, user__in=[r.user_id for r in reviews]
    ).values_list('user_id', flat=True))
    product_gallery = ProductGallery.objects.filter(product_id=single_product.id)
    related = (Product.objects.filter(category=single_product.category_id, is_available=True)
               .exclude(pk=single_product.pk).for_listing()
               .order_by(*SORTS[DEFAULT_SORT][1])[:RELATED_PRODUCTS])

    context = {
        'single_product': single_product,
        'cart_item': cart_item,
        'in_cart': in_cart,
        # how many more fit in the cart: the quantity picker never offers more than this
        'can_add': max(0, single_product.stock - in_cart_quantity),
        'in_cart_quantity': in_cart_quantity,
        'orderproduct': orderproduct,
        'reviews': reviews,
        'verified_buyers': verified_buyers,
        'rating_breakdown': _rating_breakdown(reviews),
        'product_gallery': product_gallery,
        'related_products': related,
    }
    return render(request, 'store/product_detail.html', context)


@login_required(login_url='login')
@require_POST
def submit_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    # Go back to the page the user came from, but only if it is on this site;
    # the Referer header can be missing, or point anywhere.
    referer = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        back = referer
    else:
        back = product.get_url()

    # Only people who actually bought the product may review it. The template hides the
    # form for everyone else, but a hidden form is not a check: anyone can still POST.
    if not OrderProduct.objects.filter(user=request.user, product=product, ordered=True).exists():
        messages.error(request, 'You can only review products you have bought.')
        return redirect(back)

    existing = ReviewRating.objects.filter(user=request.user, product=product).first()
    form = ReviewForm(request.POST, instance=existing)
    if form.is_valid():
        review = form.save(commit=False)
        review.user = request.user
        review.product = product
        if existing is None:
            review.ip = request.META.get('REMOTE_ADDR', '')
        review.save()
        if existing is None:
            messages.success(request, 'Thank you! Your review has been submitted.')
        else:
            messages.success(request, 'Thank you! Your review has been updated.')
    else:
        messages.error(request, 'Your review could not be saved. Please check the rating and try again.')
    return redirect(back)
