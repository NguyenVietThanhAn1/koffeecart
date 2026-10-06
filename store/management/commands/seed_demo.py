"""Fill an empty shop with demo data: categories, products (with generated photos),
variations, sale prices, past orders and reviews.

    python manage.py seed_demo
    docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py seed_demo

Safe to run again: everything is looked up by slug/email/order number first, so nothing is
duplicated, and photos are only drawn when the product has none. Product photos are generated
with Pillow, so the repository does not need to carry image files.

The demo orders belong to the review authors, so every demo review is by a real buyer (the
shop only accepts reviews from buyers) and the "sold" counts come from real order lines.
"""
import io
import textwrap
from decimal import ROUND_HALF_UP, Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from accounts.models import Account
from carts.pricing import CENT, TAX_RATE
from category.models import Category
from orders.models import Order, OrderProduct, Payment
from store.models import Product, ReviewRating, Variation

CATEGORIES = [
    ('single-origin', 'Single Origin', 'Beans from one farm or region, roasted to show where they come from.'),
    ('blends', 'Blends', 'Balanced house blends for espresso and everyday filter coffee.'),
    ('cold-brew', 'Cold Brew', 'Coarse-ground coffee made for slow, cold steeping.'),
    ('gear', 'Brewing Gear', 'Everything you need to brew at home.'),
]

# slug, name, category, price, stock, description, background colour, variations
PRODUCTS = [
    ('vietnam-robusta-dak-lak', 'Vietnam Robusta Dak Lak', 'single-origin', '12.50', 40,
     'Bold, chocolatey robusta from the Central Highlands. Classic for phin and ca phe sua da.',
     '#4a2e20', ('size', ['250g', '500g', '1kg'])),
    ('ethiopia-yirgacheffe', 'Ethiopia Yirgacheffe', 'single-origin', '18.00', 25,
     'Washed heirloom arabica with jasmine, bergamot and lemon notes. Light roast.',
     '#8c5a3c', ('size', ['250g', '500g'])),
    ('colombia-huila', 'Colombia Huila', 'single-origin', '16.00', 30,
     'Caramel sweetness, red apple and a clean finish. Medium roast.',
     '#6f4e37', ('size', ['250g', '500g', '1kg'])),
    ('sumatra-mandheling', 'Sumatra Mandheling', 'single-origin', '17.50', 0,
     'Earthy and full-bodied with cedar and dark cocoa. Back in stock soon.',
     '#3b2418', None),
    ('house-espresso', 'House Espresso Blend', 'blends', '14.00', 60,
     'Brazil and Vietnam arabica with a touch of robusta for crema. Dark chocolate, hazelnut.',
     '#2f1d14', ('size', ['250g', '500g', '1kg'])),
    ('morning-filter', 'Morning Filter Blend', 'blends', '13.00', 45,
     'Bright and easy-drinking. Made for pour-over and drip machines.',
     '#a0703f', ('size', ['250g', '500g'])),
    ('cold-brew-coarse', 'Cold Brew Coarse Grind', 'cold-brew', '15.00', 35,
     'Low-acid blend, ground coarse. Steep 18 hours for a smooth, sweet concentrate.',
     '#5b3a29', ('size', ['500g', '1kg'])),
    ('cold-brew-bags', 'Cold Brew Steeping Bags', 'cold-brew', '11.00', 50,
     'Ten ready-to-steep bags. Drop one in a jar of water, wait overnight, done.',
     '#7a5136', None),
    ('vietnamese-phin', 'Vietnamese Phin Filter', 'gear', '9.00', 80,
     'Stainless steel phin for one strong cup, the Vietnamese way.',
     '#c69c6d', None),
    ('ceramic-mug', 'Ceramic Mug 350ml', 'gear', '8.50', 70,
     'Hand-glazed stoneware mug that keeps your coffee warm.',
     '#b98b5b', ('color', ['cream', 'espresso', 'sage'])),
    ('brazil-santos', 'Brazil Santos', 'single-origin', '14.50', 55,
     'Nutty, low-acid and smooth. An easy everyday bean for any brew method.',
     '#7b4a2d', ('size', ['250g', '500g', '1kg'])),
    ('kenya-aa', 'Kenya AA', 'single-origin', '21.00', 4,
     'Juicy blackcurrant and grapefruit, bright and winey. Small lot, few bags left.',
     '#5e2f24', ('size', ['250g'])),
    ('midnight-dark-roast', 'Midnight Dark Roast', 'blends', '13.50', 38,
     'Smoky, bittersweet and heavy-bodied. Stands up to milk and sugar.',
     '#1f130d', ('size', ['250g', '500g'])),
    ('decaf-swiss-water', 'Decaf Swiss Water', 'blends', '15.50', 22,
     'Decaffeinated with water only, no chemicals. Milk chocolate and toffee.',
     '#8a6a4f', ('size', ['250g'])),
    ('cold-brew-concentrate', 'Cold Brew Concentrate 1L', 'cold-brew', '12.00', 30,
     'Ready to pour: mix one part concentrate with two parts milk or water over ice.',
     '#3f2a1f', None),
    ('hand-grinder', 'Ceramic Burr Hand Grinder', 'gear', '32.00', 15,
     'Adjustable ceramic burrs for anything from espresso to cold brew.',
     '#a97b50', None),
    ('gooseneck-kettle', 'Gooseneck Pour-over Kettle', 'gear', '28.00', 12,
     'Slow, steady pour for V60 and Chemex. Works on gas and induction.',
     '#9c6f45', ('color', ['black', 'silver'])),
]

# slug -> original price, shown struck through with a discount badge
COMPARE_AT = {
    'vietnam-robusta-dak-lak': '15.00',
    'colombia-huila': '19.00',
    'cold-brew-bags': '13.00',
    'ceramic-mug': '10.00',
    'kenya-aa': '24.00',
    'midnight-dark-roast': '16.00',
    'cold-brew-concentrate': '14.00',
    'hand-grinder': '39.00',
}

# slug -> units sold in demo orders, so "sold" counts and best sellers have something to show
SALES = {
    'vietnam-robusta-dak-lak': 124,
    'house-espresso': 86,
    'vietnamese-phin': 57,
    'ethiopia-yirgacheffe': 31,
    'cold-brew-coarse': 22,
    'ceramic-mug': 18,
    'colombia-huila': 12,
    'kenya-aa': 9,
}

REVIEWERS = [
    ('linh.demo@koffeecart.invalid', 'Linh', 'Tran'),
    ('minh.demo@koffeecart.invalid', 'Minh', 'Nguyen'),
    ('alex.demo@koffeecart.invalid', 'Alex', 'Smith'),
]

# product slug -> [(reviewer index, rating, subject, text)]
REVIEWS = {
    'vietnam-robusta-dak-lak': [(0, 5, 'Real ca phe sua da', 'Strong and chocolatey, perfect with condensed milk.'),
                                (1, 4.5, 'Great value', 'My daily phin coffee now.')],
    'ethiopia-yirgacheffe': [(2, 5, 'So floral', 'Tastes like tea and lemon. Amazing as pour-over.')],
    'house-espresso': [(1, 4, 'Good crema', 'Nice body, a bit dark for me but great with milk.'),
                       (2, 4.5, 'Solid espresso', 'Consistent shots every morning.')],
    'cold-brew-coarse': [(0, 4.5, 'Smooth', 'Very smooth, no bitterness at all.')],
    'vietnamese-phin': [(2, 4, 'Works well', 'Takes a few tries to get the grind right.')],
}


def _hex(colour):
    colour = colour.lstrip('#')
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def draw_product_photo(name, background):
    """A simple 800x800 'product shot': a kraft coffee bag with a label on a coloured background."""
    size = 800
    bg = _hex(background)
    img = Image.new('RGB', (size, size), bg)
    draw = ImageDraw.Draw(img)

    # soft lighter circle behind the bag
    light = tuple(min(255, c + 40) for c in bg)
    draw.ellipse((120, 120, 680, 680), fill=light)

    # the bag and its folded top
    kraft, kraft_dark = (205, 170, 125), (176, 140, 98)
    draw.rounded_rectangle((250, 210, 550, 640), radius=28, fill=kraft)
    draw.rectangle((250, 210, 550, 260), fill=kraft_dark)

    # the label
    draw.rounded_rectangle((280, 330, 520, 560), radius=16, fill=(248, 243, 236))
    small = ImageFont.load_default(size=22)
    title = ImageFont.load_default(size=26)
    draw.text((400, 360), 'KOFFEECART', font=small, fill=(111, 78, 55), anchor='mm')
    lines = textwrap.wrap(name, width=14)[:3]
    y = 445 - (len(lines) - 1) * 17
    for line in lines:
        draw.text((400, y), line, font=title, fill=(47, 29, 20), anchor='mm')
        y += 34

    # a coffee bean on the bag
    draw.ellipse((375, 585, 425, 620), fill=(74, 46, 32))
    draw.arc((385, 588, 415, 618), start=250, end=110, fill=(205, 170, 125), width=3)

    out = io.BytesIO()
    img.save(out, 'PNG', optimize=True)
    return out.getvalue()


def _demo_order_lines():
    """[(reviewer index, product slug, quantity)]: every reviewer bought what they reviewed,
    and the bulk of SALES goes to the reviewers in turn."""
    lines = [(who, slug, 1) for slug, entries in REVIEWS.items() for who, *_ in entries]
    lines += [(i % len(REVIEWERS), slug, qty) for i, (slug, qty) in enumerate(SALES.items())]
    return lines


def _create_demo_order(number, user, product, quantity):
    total = product.price * quantity
    tax = (total * TAX_RATE).quantize(CENT, rounding=ROUND_HALF_UP)
    payment = Payment.objects.create(
        user=user, payment_id=f'COD-{number}', payment_method='COD',
        amount_paid=total + tax, status='Completed')
    order = Order.objects.create(
        user=user, payment=payment, order_number=number,
        first_name=user.first_name, last_name=user.last_name, phone='0900000000', email=user.email,
        address_line_1='1 Demo Street', city='Ha Noi', state='Ha Noi', country='Vietnam',
        order_total=total + tax, tax=tax, status='Completed', is_ordered=True)
    OrderProduct.objects.create(
        order=order, payment=payment, user=user, product=product,
        quantity=quantity, product_price=product.price, ordered=True)


class Command(BaseCommand):
    help = 'Create demo categories, products (with generated photos), variations, orders and reviews.'

    @transaction.atomic
    def handle(self, *args, **options):
        categories = {}
        for slug, name, description in CATEGORIES:
            categories[slug], _ = Category.objects.get_or_create(
                slug=slug, defaults={'category_name': name, 'description': description})

        created = photos = 0
        products = {}
        for slug, name, cat, price, stock, description, colour, variations in PRODUCTS:
            product = Product.objects.filter(slug=slug).first()
            if product is None:
                product = Product(slug=slug, product_name=name, category=categories[cat],
                                  price=Decimal(price), stock=stock, description=description)
                created += 1
            if slug in COMPARE_AT and product.compare_at_price is None and Decimal(COMPARE_AT[slug]) > product.price:
                product.compare_at_price = Decimal(COMPARE_AT[slug])
            if not product.images or not product.images.storage.exists(product.images.name):
                # save=False: the product row is saved once, just below
                product.images.save(f'{slug}.png', ContentFile(draw_product_photo(name, colour)), save=False)
                photos += 1
            product.save()
            products[slug] = product

            if variations:
                category, values = variations
                for value in values:
                    Variation.objects.get_or_create(
                        product=product, variation_category=category, variation_value=value)

        # Review authors are inactive accounts with no usable password: they exist only
        # so the demo has star ratings, and nobody can log in as them.
        reviewers = []
        for email, first, last in REVIEWERS:
            user = Account.objects.filter(email=email).first()
            if user is None:
                user = Account.objects.create_user(
                    first_name=first, last_name=last, email=email, username=email.split('@')[0])
                user.set_unusable_password()
                user.save()
            reviewers.append(user)

        orders = 0
        for n, (who, slug, quantity) in enumerate(_demo_order_lines(), start=1):
            number = f'DEMO{n:04d}'
            if not Order.objects.filter(order_number=number).exists():
                _create_demo_order(number, reviewers[who], products[slug], quantity)
                orders += 1

        reviews = 0
        for slug, entries in REVIEWS.items():
            for who, rating, subject, text in entries:
                _, made = ReviewRating.objects.get_or_create(
                    product=products[slug], user=reviewers[who],
                    defaults={'rating': rating, 'subject': subject, 'review': text})
                reviews += made

        self.stdout.write(self.style.SUCCESS(
            f'Demo data ready: {len(categories)} categories, {len(products)} products '
            f'({created} new, {photos} photos drawn), {orders} new orders, {reviews} new reviews.'))
