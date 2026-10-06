from django import template

register = template.Library()

FULL, HALF, EMPTY = 'fas fa-star', 'fas fa-star-half-alt', 'far fa-star'


def star_icons(value):
    """Five Font Awesome classes for a 0-5 rating, rounded down to the nearest half star."""
    value = float(value or 0)
    icons = []
    for position in range(1, 6):
        if value >= position:
            icons.append(FULL)
        elif value >= position - 0.5:
            icons.append(HALF)
        else:
            icons.append(EMPTY)
    return icons


@register.inclusion_tag('includes/stars.html')
def stars(value, count=None):
    """{% stars product.averageReview product.countReview %} -> five stars and "(n)"."""
    return {'icons': star_icons(value), 'value': float(value or 0), 'count': count}


@register.filter
def compact(number):
    """1234 -> "1.2k", 25000 -> "25k" (Shopee-style sold counts)."""
    number = int(number or 0)
    if number < 1000:
        return str(number)
    value = number / 1000
    text = f'{value:.1f}'.rstrip('0').rstrip('.') if value < 10 else str(int(value))
    return f'{text}k'


@register.filter
def kc_width(percent):
    """A width class in 5% steps (kc-w-0 ... kc-w-100): bars without inline styles, which the CSP blocks."""
    step = int(round(max(0, min(100, float(percent or 0))) / 5) * 5)
    return f'kc-w-{step}'
