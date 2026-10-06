from django.db.models import Sum
from django.urls import reverse

from .models import CartItem
from .views import _owner


def counter(request):
    # The Django admin (mounted at /securelogin/) has no cart badge, so skip the queries there.
    # Compare against the real admin URL, not the word "admin", which can appear in any slug.
    if request.path.startswith(reverse('admin:index')):
        return {}

    owner = _owner(request)  # None for a guest without a cart: no query, and no session created
    if owner is None:
        return {'cart_count': 0}
    cart_count = CartItem.objects.filter(**owner).aggregate(count=Sum('quantity'))['count'] or 0
    return {'cart_count': cart_count}
