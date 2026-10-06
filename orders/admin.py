from django.contrib import admin
from .models import Payment, Order, OrderProduct


class OrderProductInline(admin.TabularInline):
    model = OrderProduct
    readonly_fields = ('payment', 'user', 'product', 'quantity', 'product_price', 'ordered')
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'full_name', 'phone', 'city', 'order_total', 'payment_status',
                    'status', 'is_ordered', 'created_at']
    # Cash on delivery: staff move orders New -> Accepted -> Completed from the list.
    list_editable = ['status']
    list_filter = ['status', 'is_ordered', 'created_at']
    search_fields = ['order_number', 'first_name', 'last_name', 'phone', 'email']
    list_select_related = ['payment']
    list_per_page = 20
    date_hierarchy = 'created_at'
    inlines = [OrderProductInline]

    @admin.display(description='Payment', ordering='payment__status')
    def payment_status(self, order):
        return order.payment.status if order.payment else '-'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'user', 'payment_method', 'amount_paid', 'status', 'created_at']
    # Mark a COD payment "Completed" once the cash is collected.
    list_editable = ['status']
    list_filter = ['status', 'payment_method']
    search_fields = ['payment_id', 'user__email']
    list_select_related = ['user']


@admin.register(OrderProduct)
class OrderProductAdmin(admin.ModelAdmin):
    list_display = ['order', 'product', 'quantity', 'product_price', 'user', 'created_at']
    list_select_related = ['order', 'product', 'user']
    search_fields = ['order__order_number', 'product__product_name']
