"""Cart totals.

Every page that shows or stores a total (cart, checkout, place_order) must call
calculate_totals(), so the tax rule lives in exactly one place.
"""
from decimal import ROUND_HALF_UP, Decimal

TAX_RATE = Decimal('0.02')  # 2%
CENT = Decimal('0.01')


def calculate_totals(cart_items):
    """Return (total, quantity, tax, grand_total) for an iterable of CartItem.

    Money is Decimal, rounded half-up to cents, so the amount shown on the cart
    page is exactly the amount saved on the order.
    """
    total = Decimal('0.00')
    quantity = 0
    for item in cart_items:
        total += item.product.price * item.quantity
        quantity += item.quantity
    tax = (total * TAX_RATE).quantize(CENT, rounding=ROUND_HALF_UP)
    return total, quantity, tax, total + tax
