from django.contrib import admin
from .models import Product, Variation, ReviewRating, ProductGallery
import admin_thumbnails

@admin_thumbnails.thumbnail('image')
class ProductGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 1

class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'category', 'price', 'compare_at_price', 'stock', 'is_available', 'modified_date')
    # Day-to-day shop work (prices, sales, restocking, hiding a product) right from the list.
    list_editable = ('price', 'compare_at_price', 'stock', 'is_available')
    list_filter = ('category', 'is_available')
    search_fields = ('product_name', 'description')
    list_select_related = ('category',)
    prepopulated_fields = {'slug': ('product_name',)}
    inlines = [ProductGalleryInline]

class VariationAdmin(admin.ModelAdmin):
    list_display = ('product', 'variation_category', 'variation_value', 'is_active')
    list_editable = ('is_active',)
    list_filter = ('product', 'variation_category', 'variation_value')

class ReviewRatingAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'subject', 'status', 'updated_at')
    # Moderation: untick "status" to hide a review from the shop.
    list_editable = ('status',)
    list_filter = ('status', 'rating')
    search_fields = ('product__product_name', 'user__email', 'subject', 'review')
    list_select_related = ('product', 'user')

admin.site.register(Product, ProductAdmin)
admin.site.register(Variation, VariationAdmin)
admin.site.register(ReviewRating, ReviewRatingAdmin)
admin.site.register(ProductGallery)