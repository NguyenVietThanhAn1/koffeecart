from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import HttpResponseBadRequest
from django.contrib import messages
from django.db import transaction
from django.urls import reverse
from carts.models import CartItem
from .forms import OrderForm
import datetime
from .models import Order, Payment, OrderProduct
import logging
import uuid
from store.models import Product
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class OutOfStock(Exception):
    pass


@login_required(login_url='login')
@require_POST
def payments(request):
    """Cash on delivery: turn a pending order into a placed order.

    Nothing that decides money or status comes from the client. The only input is
    the order number; amount, method, status and transaction id are set here.
    """
    order_number = request.POST.get('orderID', '').strip()
    if not order_number:
        return HttpResponseBadRequest('Missing orderID')

    try:
        with transaction.atomic():
            # Lock the order row so a double submit cannot place it twice.
            order = Order.objects.select_for_update().filter(
                user=request.user, is_ordered=False, order_number=order_number
            ).first()
            if order is None:
                return HttpResponseBadRequest('Order not found')

            cart_items = list(CartItem.objects.filter(user=request.user))
            if not cart_items:
                return HttpResponseBadRequest('Cart is empty')

            # Lock the products, then check stock before changing anything.
            products = Product.objects.select_for_update().in_bulk(
                [item.product_id for item in cart_items])
            needed = {}
            for item in cart_items:
                needed[item.product_id] = needed.get(item.product_id, 0) + item.quantity
            for product_id, qty in needed.items():
                if products[product_id].stock < qty:
                    raise OutOfStock(products[product_id].product_name)

            payment = Payment.objects.create(
                user=request.user,
                payment_id='COD-' + uuid.uuid4().hex[:12].upper(),
                payment_method='COD',
                amount_paid=order.order_total,
                status='Pending',  # cash is collected on delivery
            )
            order.payment = payment
            order.is_ordered = True
            order.save()

            for item in cart_items:
                orderproduct = OrderProduct.objects.create(
                    order=order,
                    payment=payment,
                    user=request.user,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    product_price=item.product.price,
                    ordered=True,
                )
                orderproduct.variations.set(item.variations.all())
                products[item.product_id].stock -= item.quantity

            for product in products.values():
                product.save()
            CartItem.objects.filter(user=request.user).delete()
    except OutOfStock as exc:
        messages.error(request, f'Sorry, "{exc}" does not have enough stock.')
        return redirect('cart')

    # Email is best effort: the order is already saved, so an SMTP failure must not undo it.
    try:
        message = render_to_string('orders/order_recieved_email.html', {
            'user': request.user,
            'order': order,
        })
        EmailMessage('Thank you for your order!', message, to=[request.user.email]).send()
    except Exception:
        logger.exception('Could not send order email for order %s', order.order_number)

    return redirect(
        reverse('order_complete') + f'?order_number={order.order_number}&payment_id={payment.payment_id}')


@login_required(login_url='login')
def place_order(request, total=0, quantity=0,):
    current_user = request.user

    # If the cart count is less than or equal to 0, then redirect back to shop
    cart_items = CartItem.objects.filter(user=current_user)
    cart_count = cart_items.count()
    if cart_count <= 0:
        return redirect('store')

    grand_total = 0
    tax = 0
    for cart_item in cart_items:
        total += (cart_item.product.price * cart_item.quantity)
        quantity += cart_item.quantity
    tax = (2 * total)/100
    grand_total = total + tax

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            # Store all the billing information inside Order table
            data = Order()
            data.user = current_user
            data.first_name = form.cleaned_data['first_name']
            data.last_name = form.cleaned_data['last_name']
            data.phone = form.cleaned_data['phone']
            data.email = form.cleaned_data['email']
            data.address_line_1 = form.cleaned_data['address_line_1']
            data.address_line_2 = form.cleaned_data['address_line_2']
            data.country = form.cleaned_data['country']
            data.state = form.cleaned_data['state']
            data.city = form.cleaned_data['city']
            data.order_note = form.cleaned_data['order_note']
            data.order_total = grand_total
            data.tax = tax
            data.ip = request.META.get('REMOTE_ADDR')
            data.save()
            # Generate order number
            yr = int(datetime.date.today().strftime('%Y'))
            dt = int(datetime.date.today().strftime('%d'))
            mt = int(datetime.date.today().strftime('%m'))
            d = datetime.date(yr,mt,dt)
            current_date = d.strftime("%Y%m%d") #20210305
            order_number = current_date + str(data.id)
            data.order_number = order_number
            data.save()

            order = Order.objects.get(user=current_user, is_ordered=False, order_number=order_number)
            context = {
                'order': order,
                'cart_items': cart_items,
                'total': total,
                'tax': tax,
                'grand_total': grand_total,
            }
            return render(request, 'orders/payments.html', context)
    else:
        return redirect('checkout')


@login_required(login_url='login')
def order_complete(request):
    order_number = request.GET.get('order_number')
    transID = request.GET.get('payment_id')

    try:
        order = Order.objects.get(order_number=order_number, user=request.user, is_ordered=True)
        ordered_products = OrderProduct.objects.filter(order_id=order.id)

        subtotal = 0
        for i in ordered_products:
            subtotal += i.product_price * i.quantity

        payment = Payment.objects.get(payment_id=transID)

        context = {
            'order': order,
            'ordered_products': ordered_products,
            'order_number': order.order_number,
            'transID': payment.payment_id,
            'payment': payment,
            'subtotal': subtotal,
        }
        return render(request, 'orders/order_complete.html', context)
    except (Payment.DoesNotExist, Order.DoesNotExist):
        return redirect('home')