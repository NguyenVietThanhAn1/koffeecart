"""The seed_demo command fills an empty shop and is safe to run again."""
from io import StringIO

import pytest
from django.core.management import call_command
from PIL import Image

from accounts.models import Account
from category.models import Category
from store.models import Product, ReviewRating, Variation


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path  # generated photos go to a throwaway folder
    return tmp_path


def _seed():
    out = StringIO()
    call_command('seed_demo', stdout=out)
    return out.getvalue()


def test_seed_creates_a_browsable_shop(db, media):
    _seed()
    assert Category.objects.count() == 4
    assert Product.objects.count() == 10
    assert Product.objects.filter(stock=0).exists()          # one "sold out" product to show
    assert Variation.objects.filter(variation_category='size').exists()
    assert ReviewRating.objects.exists()
    for product in Product.objects.all():
        path = media / product.images.name
        assert path.exists(), product.slug
        with Image.open(path) as img:
            assert img.size == (800, 800)


def test_seed_is_idempotent(db, media):
    _seed()
    counts = (Product.objects.count(), Variation.objects.count(), ReviewRating.objects.count(),
              Account.objects.count())
    files = sorted(p.name for p in (media / 'photos' / 'products').iterdir())
    output = _seed()
    assert (Product.objects.count(), Variation.objects.count(), ReviewRating.objects.count(),
            Account.objects.count()) == counts
    assert sorted(p.name for p in (media / 'photos' / 'products').iterdir()) == files  # no new photos
    assert '0 new' in output


def test_seed_redraws_a_missing_photo(db, media):
    _seed()
    product = Product.objects.get(slug='colombia-huila')
    (media / product.images.name).unlink()
    _seed()
    product.refresh_from_db()
    assert (media / product.images.name).exists()


def test_review_authors_cannot_log_in(db, media):
    _seed()
    authors = Account.objects.filter(reviewrating__isnull=False).distinct()
    assert authors.exists()
    for user in authors:
        assert not user.is_active
        assert not user.has_usable_password()


def test_seeded_shop_pages_render(client, db, media):
    _seed()
    product = Product.objects.filter(stock__gt=0).first()
    assert client.get('/').status_code == 200
    assert client.get(product.get_url()).status_code == 200
    assert b'Sold out' in client.get('/store/').content
