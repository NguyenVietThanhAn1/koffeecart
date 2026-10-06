from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from category.models import Category
from django.urls import reverse
from accounts.models import Account
from django.db.models import Avg, Count, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

# Create your models here.

class ProductQuerySet(models.QuerySet):
    def with_ratings(self):
        """Add avg_rating and review_count to every product in the same query.

        List pages show the stars for many products; without this each product would
        run its own two queries (the N+1 problem).
        """
        published = Q(reviewrating__status=True)
        return self.annotate(
            avg_rating=Avg('reviewrating__rating', filter=published),
            review_count=Count('reviewrating', filter=published),
        )

    def with_sales(self):
        """Add sold = units in placed orders.

        A subquery, not a join: joining order lines next to the reviews joined by
        with_ratings() would multiply the rows and inflate both counts.
        """
        from orders.models import OrderProduct  # orders imports this module

        sold = (OrderProduct.objects.filter(product=OuterRef('pk'), ordered=True)
                .values('product').annotate(total=Sum('quantity')).values('total'))
        return self.annotate(sold=Coalesce(Subquery(sold), Value(0)))

    def for_listing(self):
        """Everything a product card shows, in one query for any number of products."""
        return self.select_related('category').with_ratings().with_sales()


class Product(models.Model):
    product_name    = models.CharField(max_length=200, unique=True)
    slug            = models.SlugField(max_length=200, unique=True)
    description     = models.TextField(max_length=500, blank=True)
    price           = models.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Original price, shown struck through next to the price. Leave empty when not on sale.')
    images          = models.ImageField(upload_to='photos/products')
    stock           = models.IntegerField()
    is_available    = models.BooleanField(default=True)
    category        = models.ForeignKey(Category, on_delete=models.CASCADE)
    created_date    = models.DateTimeField(auto_now_add=True)
    modified_date   = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        constraints = [
            # A "was" price lower than the price would show a fake discount.
            models.CheckConstraint(
                condition=Q(compare_at_price__isnull=True) | Q(compare_at_price__gt=models.F('price')),
                name='product_compare_at_price_above_price',
            ),
        ]

    def clean(self):
        if self.compare_at_price is not None and self.price is not None and self.compare_at_price <= self.price:
            raise ValidationError({'compare_at_price': 'Must be higher than the price, or empty.'})

    @property
    def discount_percent(self):
        """Whole-number discount off compare_at_price, 0 when not on sale."""
        if not self.compare_at_price or self.compare_at_price <= self.price:
            return 0
        off = (self.compare_at_price - self.price) * 100 / self.compare_at_price
        return int(off.quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def get_url(self):
        return reverse('product_detail', args=[self.category.slug, self.slug])

    def __str__(self):
        return self.product_name

    def averageReview(self):
        # Products loaded with Product.objects.with_ratings() already carry the value.
        if hasattr(self, 'avg_rating'):
            return float(self.avg_rating or 0)
        reviews = ReviewRating.objects.filter(product=self, status=True).aggregate(average=Avg('rating'))
        avg = 0
        if reviews['average'] is not None:
            avg = float(reviews['average'])
        return avg

    def countReview(self):
        if hasattr(self, 'review_count'):
            return self.review_count
        return ReviewRating.objects.filter(product=self, status=True).count()

class VariationManager(models.Manager):
    def colors(self):
        return super(VariationManager, self).filter(variation_category='color', is_active=True)

    def sizes(self):
        return super(VariationManager, self).filter(variation_category='size', is_active=True)

variation_category_choice = (
    ('color', 'color'),
    ('size', 'size'),
)

class Variation(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variation_category = models.CharField(max_length=100, choices=variation_category_choice)
    variation_value     = models.CharField(max_length=100)
    is_active           = models.BooleanField(default=True)
    created_date        = models.DateTimeField(auto_now=True)

    objects = VariationManager()

    def __str__(self):
        return self.variation_value


class ReviewRating(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(Account, on_delete=models.CASCADE)
    subject = models.CharField(max_length=100, blank=True)
    review = models.TextField(max_length=500, blank=True)
    # The star widget offers 0.5 to 5 in half steps.
    rating = models.FloatField(validators=[MinValueValidator(0.5), MaxValueValidator(5)])
    ip = models.CharField(max_length=20, blank=True)
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # submit_review updates the existing review; the database makes sure of it.
            models.UniqueConstraint(fields=['user', 'product'], name='one_review_per_user_and_product'),
        ]

    def __str__(self):
        return self.subject


class ProductGallery(models.Model):
    product = models.ForeignKey(Product, default=None, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='store/products', max_length=255)

    def __str__(self):
        return self.product.product_name

    class Meta:
        verbose_name = 'productgallery'
        verbose_name_plural = 'product gallery'