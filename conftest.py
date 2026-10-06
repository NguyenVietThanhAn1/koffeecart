import pytest


def _make_user(email, username):
    from accounts.models import Account
    user = Account.objects.create_user(
        first_name='Test', last_name=username, username=username,
        email=email, password='S3cure-pass-123',
    )
    user.is_active = True
    user.save()
    return user


@pytest.fixture
def user_a(db):
    return _make_user('a@example.com', 'usera')


@pytest.fixture
def user_b(db):
    return _make_user('b@example.com', 'userb')


@pytest.fixture
def product(db):
    from category.models import Category
    from store.models import Product
    cat = Category.objects.create(category_name='Beans', slug='beans')
    return Product.objects.create(
        product_name='Arabica', slug='arabica', price=100, stock=5,
        category=cat, images='photos/products/x.jpg',
    )


@pytest.fixture
def make_order(db):
    """Create an Order (default: paid) owned by the given user."""
    from orders.models import Order, Payment

    def _make(user, number='202601011', paid=True):
        order = Order.objects.create(
            user=user, order_number=number, first_name='A', last_name='B',
            phone='123', email=user.email, address_line_1='Secret street 1',
            country='VN', state='HCM', city='HCM', order_total=102.0, tax=2.0,
            is_ordered=paid,
        )
        if paid:
            order.payment = Payment.objects.create(
                user=user, payment_id='PAY-' + number, payment_method='PayPal',
                amount_paid='102.0', status='COMPLETED')
            order.save()
        return order
    return _make


@pytest.fixture
def order_with_cart(db, product, make_order):
    """A pending (unpaid) order plus a cart line: returns a factory(user, qty)."""
    from carts.models import CartItem

    def _make(user, qty=1, number='202601012'):
        from carts.pricing import calculate_totals
        order = make_order(user, number=number, paid=False)
        item = CartItem.objects.create(user=user, product=product, quantity=qty)
        # Same totals that place_order would have saved for this cart.
        _, _, order.tax, order.order_total = calculate_totals([item])
        order.save()
        return order
    return _make


@pytest.fixture
def buy(db, make_order):
    """Record that a user has bought a product (a placed order that contains it)."""
    from orders.models import OrderProduct
    counter = {'n': 0}

    def _buy(user, product):
        counter['n'] += 1
        order = make_order(user, number=f'20260201{counter["n"]}', paid=True)
        return OrderProduct.objects.create(
            order=order, payment=order.payment, user=user, product=product,
            quantity=1, product_price=product.price, ordered=True)
    return _buy


@pytest.fixture
def make_product(db):
    """Factory for extra products (unique name and slug per call)."""
    from decimal import Decimal
    from category.models import Category
    from store.models import Product
    counter = {'n': 0}

    def _make(price='10.00', stock=10, slug=None):
        counter['n'] += 1
        n = counter['n']
        cat, _ = Category.objects.get_or_create(slug='beans', defaults={'category_name': 'Beans'})
        return Product.objects.create(
            product_name=f'Product {n}', slug=slug or f'product-{n}', price=Decimal(price),
            stock=stock, category=cat, images='photos/products/x.jpg',
        )
    return _make
