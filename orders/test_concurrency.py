"""Concurrency checks for the COD payment view.

select_for_update() only really locks rows on PostgreSQL (SQLite ignores it), so these tests
are skipped locally on SQLite and run in CI against the postgres service.
"""
import threading

import pytest
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from carts.models import CartItem
from orders.models import Order, Payment

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='row locks need PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def _pay_concurrently(users_and_orders):
    """Each (user, order_number) pays at the same moment; returns [(status, location), ...]."""
    barrier = threading.Barrier(len(users_and_orders))
    results = []
    lock = threading.Lock()

    def worker(user, order_number):
        try:
            client = Client()
            client.force_login(user)
            barrier.wait(timeout=15)
            resp = client.post(reverse('payments'), {'orderID': order_number})
            with lock:
                results.append((resp.status_code, resp.get('Location', '')))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=pair) for pair in users_and_orders]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == len(users_and_orders), 'a payment request hung or crashed'
    return results


def test_two_simultaneous_payments_of_one_order_place_it_once(user_a, product, order_with_cart):
    order = order_with_cart(user_a)
    results = _pay_concurrently([(user_a, order.order_number)] * 2)

    assert sorted(status for status, _ in results) == [302, 400]
    product.refresh_from_db()
    assert product.stock == 4  # decremented once, not twice
    assert Payment.objects.count() == 1
    assert Order.objects.filter(is_ordered=True).count() == 1


def test_last_item_cannot_be_sold_to_two_people(user_a, user_b, product, make_order):
    product.stock = 1
    product.save()
    orders = []
    for user, number in ((user_a, '202601011'), (user_b, '202601012')):
        orders.append((user, make_order(user, number=number, paid=False).order_number))
        CartItem.objects.create(user=user, product=product, quantity=1)

    results = _pay_concurrently(orders)

    locations = sorted(location.split('?')[0] for _, location in results)
    assert locations == [reverse('cart'), reverse('order_complete')]  # one bought, one told "no stock"
    product.refresh_from_db()
    assert product.stock == 0  # never negative
    assert Order.objects.filter(is_ordered=True).count() == 1
