from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.models import UserProfile
from store.models import Product, Variation
from .models import Cart, CartItem
from .pricing import calculate_totals


def _cart_id(request, create=False):
    """The guest cart id, which is the session key.

    Only adding to the cart creates a session (create=True). Merely looking at pages must
    not: otherwise every anonymous visitor and every crawler request writes a session row.
    session.create() returns None; the new key is on the session afterwards.
    """
    if create and not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _line_key(item):
    """Two cart lines are "the same" when product and set of variations are equal (order does not matter)."""
    return item.product_id, frozenset(v.id for v in item.variations.all())


def _owner(request, create=False):
    """Filter kwargs for the current cart: the user's lines, or the guest cart's lines.

    Returns None for a guest who has no cart yet (and create is False).
    """
    if request.user.is_authenticated:
        return {'user': request.user}
    cart_id = _cart_id(request, create=create)
    if not cart_id:
        return None
    if create:
        # filter().first(): an old race may have left two Cart rows with the same id
        cart = Cart.objects.filter(cart_id=cart_id).first() or Cart.objects.create(cart_id=cart_id)
        return {'cart': cart}
    return {'cart__cart_id': cart_id}


def _cart_items(request):
    """Active cart lines with everything the templates show, in a fixed number of queries."""
    owner = _owner(request)
    if owner is None:
        return CartItem.objects.none()
    return (CartItem.objects.filter(is_active=True, **owner)
            .select_related('product__category')   # product.get_url() needs the category slug
            .prefetch_related('variations')
            .order_by('id'))


def merge_guest_cart(cart_id, user):
    """Move the guest cart into the user's cart when they log in.

    A guest line that matches one of the user's lines adds its quantity to it;
    any other guest line simply becomes the user's.
    """
    if not cart_id:
        return
    guest_lines = CartItem.objects.filter(cart__cart_id=cart_id, user__isnull=True).prefetch_related('variations')
    with transaction.atomic():
        user_lines = {
            _line_key(line): line
            for line in CartItem.objects.filter(user=user).prefetch_related('variations')
        }
        for guest in guest_lines:
            key = _line_key(guest)
            if key in user_lines:
                mine = user_lines[key]
                mine.quantity += guest.quantity
                mine.save()
                guest.delete()
            else:
                guest.user = user
                guest.save()
                user_lines[key] = guest


def _find_cart_item(request, product_id, cart_item_id):
    """The cart line if it belongs to the current user or guest cart, otherwise None."""
    owner = _owner(request)
    if owner is None:
        return None
    return CartItem.objects.filter(product_id=product_id, id=cart_item_id, **owner).first()


def _variations_from_post(request, product):
    """Variations named by the POSTed fields, e.g. color=Red.

    Fields that are not variations of this product (csrfmiddlewaretoken, ...) are ignored.
    """
    variations = []
    for key, value in request.POST.items():
        variation = Variation.objects.filter(
            product=product, variation_category__iexact=key, variation_value__iexact=value
        ).first()
        if variation is not None:
            variations.append(variation)
    return variations


MAX_QUANTITY_PER_ADD = 99


def _requested_quantity(request):
    """The "quantity" field of the product page (1 when missing or not a sensible number)."""
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        return 1
    return min(max(quantity, 1), MAX_QUANTITY_PER_ADD)


@require_POST
def add_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_available=True)  # hidden products cannot be added
    owner = _owner(request, create=True)
    lines = CartItem.objects.filter(product=product, **owner).prefetch_related('variations')

    # The cart may not hold more of a product than is in stock (all its variations together).
    in_cart = lines.aggregate(n=Sum('quantity'))['n'] or 0
    available = product.stock - in_cart
    if available <= 0:
        if product.stock <= 0:
            messages.error(request, f'Sorry, "{product.product_name}" is out of stock.')
        else:
            messages.error(request, f'Sorry, only {product.stock} of "{product.product_name}" in stock.')
        return redirect('cart' if in_cart else product.get_url())

    quantity = _requested_quantity(request)
    if quantity > available:
        quantity = available
        messages.warning(request, f'Only {available} more "{product.product_name}" available, so {available} added.')

    variations = _variations_from_post(request, product)
    key = (product.id, frozenset(v.id for v in variations))
    line = next((line for line in lines if _line_key(line) == key), None)
    if line is not None:
        line.quantity += quantity
        line.save()
    else:
        line = CartItem.objects.create(product=product, quantity=quantity, **owner)
        line.variations.set(variations)

    # "Buy now" goes straight to checkout (which asks guests to sign in first).
    return redirect('checkout' if request.POST.get('buy_now') else 'cart')


@require_POST
def remove_cart(request, product_id, cart_item_id):
    # A missing line (already removed, or someone else's) is a no-op: the cart is already as asked.
    cart_item = _find_cart_item(request, product_id, cart_item_id)
    if cart_item is not None:
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
            cart_item.save()
        else:
            cart_item.delete()
    return redirect('cart')


@require_POST
def remove_cart_item(request, product_id, cart_item_id):
    cart_item = _find_cart_item(request, product_id, cart_item_id)
    if cart_item is not None:
        cart_item.delete()
    return redirect('cart')


def _cart_page(request, template, **extra):
    cart_items = _cart_items(request)
    total, quantity, tax, grand_total = calculate_totals(cart_items)
    return render(request, template, {
        'cart_items': cart_items,
        'total': total,
        'quantity': quantity,
        'tax': tax,
        'grand_total': grand_total,
        **extra,
    })


def cart(request):
    return _cart_page(request, 'store/cart.html')


@login_required(login_url='login')
def checkout(request):
    # The address saved in the profile pre-fills the delivery form (Shopee's "default address").
    profile = UserProfile.objects.filter(user=request.user).first()
    return _cart_page(request, 'store/checkout.html', profile=profile)
