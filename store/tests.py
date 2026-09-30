import pytest
from django.urls import reverse


# S4 — submit_review needs login and POST
def test_submit_review_requires_login(client, product):
    resp = client.post(reverse('submit_review', args=[product.id]),
                       {'subject': 's', 'review': 'r', 'rating': 5})
    assert resp.status_code == 302
    assert resp['Location'].startswith(reverse('login'))


def test_submit_review_rejects_get(client, user_a, product):
    client.force_login(user_a)
    assert client.get(reverse('submit_review', args=[product.id])).status_code == 405
