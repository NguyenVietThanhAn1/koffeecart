from django.db.models import Sum
from django.urls import reverse

from .models import CartItem
from .views import _cart_id


def counter(request):
    # The Django admin (mounted at /securelogin/) has no cart badge, so skip the queries there.
    # Compare against the real admin URL, not the word "admin", which can appear in any slug.
    if request.path.startswith(reverse('admin:index')):
        return {}

    if request.user.is_authenticated:
        cart_items = CartItem.objects.filter(user=request.user)
    else:
        cart_items = CartItem.objects.filter(cart__cart_id=_cart_id(request))
    cart_count = cart_items.aggregate(count=Sum('quantity'))['count'] or 0
    return {'cart_count': cart_count}
