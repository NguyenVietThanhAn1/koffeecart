from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from store.models import Product, Variation
from .models import Cart, CartItem
from .pricing import calculate_totals


def _cart_id(request):
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart


def _cart_items(request):
    """Active cart lines: the logged-in user's, or the guest cart tied to the session."""
    lines = CartItem.objects.filter(is_active=True).select_related('product')
    if request.user.is_authenticated:
        return lines.filter(user=request.user)
    return lines.filter(cart__cart_id=_cart_id(request))


def _find_cart_item(request, product_id, cart_item_id):
    """The cart line if it belongs to the current user or guest cart, otherwise None."""
    lines = CartItem.objects.filter(product_id=product_id, id=cart_item_id)
    if request.user.is_authenticated:
        return lines.filter(user=request.user).first()
    return lines.filter(cart__cart_id=_cart_id(request)).first()


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


@require_POST
def add_cart(request, product_id):
    current_user = request.user
    product = get_object_or_404(Product, id=product_id)
    product_variation = _variations_from_post(request, product)

    # If the user is authenticated
    if current_user.is_authenticated:
        is_cart_item_exists = CartItem.objects.filter(product=product, user=current_user).exists()
        if is_cart_item_exists:
            cart_item = CartItem.objects.filter(product=product, user=current_user)
            ex_var_list = []
            id = []
            for item in cart_item:
                existing_variation = item.variations.all()
                ex_var_list.append(list(existing_variation))
                id.append(item.id)

            if product_variation in ex_var_list:
                # increase the cart item quantity
                index = ex_var_list.index(product_variation)
                item_id = id[index]
                item = CartItem.objects.get(product=product, id=item_id)
                item.quantity += 1
                item.save()

            else:
                item = CartItem.objects.create(product=product, quantity=1, user=current_user)
                if len(product_variation) > 0:
                    item.variations.clear()
                    item.variations.add(*product_variation)
                item.save()
        else:
            cart_item = CartItem.objects.create(
                product = product,
                quantity = 1,
                user = current_user,
            )
            if len(product_variation) > 0:
                cart_item.variations.clear()
                cart_item.variations.add(*product_variation)
            cart_item.save()
        return redirect('cart')
    # If the user is not authenticated
    else:
        try:
            cart = Cart.objects.get(cart_id=_cart_id(request)) # get the cart using the cart_id present in the session
        except Cart.DoesNotExist:
            cart = Cart.objects.create(
                cart_id = _cart_id(request)
            )
        cart.save()

        is_cart_item_exists = CartItem.objects.filter(product=product, cart=cart).exists()
        if is_cart_item_exists:
            cart_item = CartItem.objects.filter(product=product, cart=cart)
            # existing_variations -> database
            # current variation -> product_variation
            # item_id -> database
            ex_var_list = []
            id = []
            for item in cart_item:
                existing_variation = item.variations.all()
                ex_var_list.append(list(existing_variation))
                id.append(item.id)

            if product_variation in ex_var_list:
                # increase the cart item quantity
                index = ex_var_list.index(product_variation)
                item_id = id[index]
                item = CartItem.objects.get(product=product, id=item_id)
                item.quantity += 1
                item.save()

            else:
                item = CartItem.objects.create(product=product, quantity=1, cart=cart)
                if len(product_variation) > 0:
                    item.variations.clear()
                    item.variations.add(*product_variation)
                item.save()
        else:
            cart_item = CartItem.objects.create(
                product = product,
                quantity = 1,
                cart = cart,
            )
            if len(product_variation) > 0:
                cart_item.variations.clear()
                cart_item.variations.add(*product_variation)
            cart_item.save()
        return redirect('cart')


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


def cart(request):
    cart_items = _cart_items(request)
    total, quantity, tax, grand_total = calculate_totals(cart_items)

    context = {
        'total': total,
        'quantity': quantity,
        'cart_items': cart_items,
        'tax'       : tax,
        'grand_total': grand_total,
    }
    return render(request, 'store/cart.html', context)


@login_required(login_url='login')
def checkout(request):
    cart_items = _cart_items(request)
    total, quantity, tax, grand_total = calculate_totals(cart_items)

    context = {
        'total': total,
        'quantity': quantity,
        'cart_items': cart_items,
        'tax'       : tax,
        'grand_total': grand_total,
    }
    return render(request, 'store/checkout.html', context)
