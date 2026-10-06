"""Filtering and sorting for product listings (store, category and search pages).

All input comes from the query string, so it is validated by a form: a bad value
(?min_price=abc, ?sort=drop_table) is simply ignored instead of causing an error.
"""
from django import forms
from django.db.models import F

SORTS = {
    # key: (label, ordering). "id" last keeps pagination stable when values tie.
    'popular': ('Popular', (F('sold').desc(), F('avg_rating').desc(nulls_last=True), 'id')),
    'newest': ('Latest', ('-created_date', 'id')),
    'sales': ('Top sales', (F('sold').desc(), 'id')),
    'rating': ('Top rated', (F('avg_rating').desc(nulls_last=True), F('review_count').desc(), 'id')),
    'price_asc': ('Price: low to high', ('price', 'id')),
    'price_desc': ('Price: high to low', ('-price', 'id')),
}
DEFAULT_SORT = 'popular'


class ProductFilterForm(forms.Form):
    keyword = forms.CharField(required=False, max_length=100, strip=True)
    category = forms.SlugField(required=False)
    sort = forms.ChoiceField(required=False, choices=[(k, v[0]) for k, v in SORTS.items()])
    min_price = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2)
    max_price = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2)
    rating = forms.TypedChoiceField(required=False, coerce=int, empty_value=None,
                                    choices=[('', 'Any'), ('4', '4 stars & up'), ('3', '3 stars & up')])
    in_stock = forms.BooleanField(required=False)
    on_sale = forms.BooleanField(required=False)

    def values(self):
        """The valid fields only; invalid ones are dropped, not raised."""
        self.is_valid()
        return {name: value for name, value in self.cleaned_data.items() if value not in (None, '', False)}


def apply_filters(products, values):
    """Filter and order a for_listing() queryset with ProductFilterForm.values()."""
    if 'min_price' in values:
        products = products.filter(price__gte=values['min_price'])
    if 'max_price' in values:
        products = products.filter(price__lte=values['max_price'])
    if 'rating' in values:
        products = products.filter(avg_rating__gte=values['rating'])
    if values.get('in_stock'):
        products = products.filter(stock__gt=0)
    if values.get('on_sale'):
        products = products.filter(compare_at_price__gt=F('price'))
    sort = values.get('sort', DEFAULT_SORT)
    return products.order_by(*SORTS[sort][1])
