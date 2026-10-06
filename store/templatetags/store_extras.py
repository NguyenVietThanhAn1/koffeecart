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
