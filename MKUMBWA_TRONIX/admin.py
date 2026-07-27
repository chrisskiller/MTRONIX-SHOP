from django.contrib import admin
from .models import Notification
from .models import TechnicianProfile
from .models import (
    TechnicianProfile, ServiceType, ServiceRequest,
    ServiceStatusHistory, ServiceDeliveryAsset,
    Category, Product, Payment
)

@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(admin.ModelAdmin):
    # 🌟 FIXED: Mapped exact model field attributes explicitly
    list_display = ('user', 'employee_id', 'specialty', 'is_active_bench')
    list_filter = ('is_active_bench', 'specialty')
    search_fields = ('user__username', 'employee_id')


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'base_price', 'estimated_hours', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)


class ServiceStatusHistoryInline(admin.TabularInline):
    model = ServiceStatusHistory
    extra = 0
    readonly_fields = ('timestamp', 'changed_by', 'status', 'internal_note')


class ServiceDeliveryAssetInline(admin.StackedInline):
    model = ServiceDeliveryAsset
    extra = 0


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'device_model', 'service_type', 'channel', 'priority', 'status', 'created_at')
    list_filter = ('status', 'channel', 'priority', 'service_type__category')
    search_fields = ('customer__username', 'device_model', 'serial_or_imei')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ServiceStatusHistoryInline, ServiceDeliveryAssetInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'price', 'stock', 'is_available')
    list_filter = ('category', 'is_available')
    search_fields = ('name',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'method', 'status', 'transaction_ref', 'created_at')
    list_filter = ('method', 'status')
    search_fields = ('customer__username', 'transaction_ref')

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('recipient__username', 'title')


from .models import GalleryPost, WorkUpdate

@admin.register(GalleryPost)
class GalleryPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'device_model', 'is_featured', 'created_at')
    list_filter = ('category', 'is_featured')
    search_fields = ('title', 'device_model')
    readonly_fields = ('created_at',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(WorkUpdate)
class WorkUpdateAdmin(admin.ModelAdmin):
    list_display = ('title', 'post_type', 'is_published', 'created_at')
    list_filter = ('post_type', 'is_published')
    search_fields = ('title', 'content')
    readonly_fields = ('created_at',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)