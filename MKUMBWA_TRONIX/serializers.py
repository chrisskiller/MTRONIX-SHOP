from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from .models import (
    TechnicianProfile, ServiceType, ServiceRequest,
    ServiceStatusHistory, ServiceDeliveryAsset,
    Category, Product, Payment, Notification,
    GalleryPost, WorkUpdate, Message,
    InventoryItem, Accessory, PartsConsumption
)

User = get_user_model()


# ─────────────────────────────────────────────
# CUSTOM TOKEN SERIALIZER (FOR ROLE DECODING)
# ─────────────────────────────────────────────

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """ 
    Custom Simple JWT serializer to inject user roles inside token payloads.
    This allows the frontend to immediately redirect based on role.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        
        # Inject custom payload claims for frontend role checking
        # Assuming your User model has 'role', 'phone', etc.
        if hasattr(user, 'role'):
            token['role'] = user.role
        else:
            # Fallback if role is not directly on the model (e.g. TechnicianProfile)
            token['role'] = 'CUSTOMER' # Default assumption
            
        token['username'] = user.username
        token['first_name'] = user.first_name or user.username
        return token


# ─────────────────────────────────────────────
# USER SERIALIZER
# ─────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        # Include custom fields from your User model
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role', 'phone', 'address')
        read_only_fields = ('role',)


# ─────────────────────────────────────────────
# TECHNICIAN PROFILE
# ─────────────────────────────────────────────

class TechnicianProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    specialization_display = serializers.CharField(source='get_specialization_display', read_only=True)

    class Meta:
        model = TechnicianProfile
        fields = '__all__'


# ─────────────────────────────────────────────
# SERVICE TYPE
# ─────────────────────────────────────────────

class ServiceTypeSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = ServiceType
        fields = '__all__'


# ─────────────────────────────────────────────
# SERVICE STATUS HISTORY
# ─────────────────────────────────────────────

class ServiceStatusHistorySerializer(serializers.ModelSerializer):
    changed_by = UserSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ServiceStatusHistory
        fields = '__all__'


# ─────────────────────────────────────────────
# SERVICE REQUEST
# ─────────────────────────────────────────────

class ServiceRequestSerializer(serializers.ModelSerializer):
    # Parties involved (Read-only for detail views)
    customer = UserSerializer(read_only=True)
    technician = UserSerializer(read_only=True) # Renamed to match model update
    created_by = UserSerializer(read_only=True)

    # Computed financial fields
    amount_paid = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()
    parts_cost = serializers.SerializerMethodField()

    def get_amount_paid(self, obj):
        total = obj.payments.filter(status='CONFIRMED').aggregate(t=Sum('amount'))['t'] or 0
        return total

    def get_balance_due(self, obj):
        owed = obj.final_price if obj.final_price is not None else obj.quoted_price
        if owed is None:
            return None
        return owed - self.get_amount_paid(obj)

    def get_parts_cost(self, obj):
        total = obj.parts_used.aggregate(
            total=Sum(ExpressionWrapper(
                F('quantity_used') * F('inventory_item__unit_cost'),
                output_field=DecimalField()
            ))
        )['total']
        return total or 0

    # ID fields for writing (Creating/Updating)
    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='customer', write_only=True, required=False, allow_null=True
    )
    # Technician assignment is handled by special Tech View logic, not generic write.
    technician_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='technician', write_only=True, required=False, allow_null=True
    )

    # Nested display for detail views
    service_type = ServiceTypeSerializer(read_only=True)
    service_type_id = serializers.PrimaryKeyRelatedField(
         queryset=ServiceType.objects.all(), source='service_type', write_only=True,
         required=False, allow_null=True
     )
    status_history = ServiceStatusHistorySerializer(many=True, read_only=True)

    # Choice display helpers
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model = ServiceRequest
        # All fields included for convenience, read-only handling applied where needed
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'completed_at', 'created_by')

# ─────────────────────────────────────────────
# CHAT MESSAGES
# ─────────────────────────────────────────────

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ('id', 'service_request', 'sender_role', 'sender_display_name', 'body', 'created_at')
        read_only_fields = ('id', 'created_at')

# ─────────────────────────────────────────────
# SERVICE DELIVERY ASSET
# ─────────────────────────────────────────────

class ServiceDeliveryAssetSerializer(serializers.ModelSerializer):
    service_request_id = serializers.PrimaryKeyRelatedField(
        queryset=ServiceRequest.objects.all(), source='service_request', write_only=True
    )

    class Meta:
        model = ServiceDeliveryAsset
        # service_request nested serializer is removed to simplify writes
        fields = '__all__'


# ─────────────────────────────────────────────
# INVENTORY / PRODUCTS
# ─────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True
    )
    in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = '__all__'


# ─────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────

class PaymentSerializer(serializers.ModelSerializer):
    customer = UserSerializer(read_only=True)
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('created_at', 'paid_at', 'customer')


# ─────────────────────────────────────────────
# NOTIFICATIONS & ASSETS
# ─────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_notification_type_display', read_only=True)

    class Meta:
        model = Notification
        fields = '__all__'
        read_only_fields = ('created_at', 'recipient')


class GalleryPostSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = GalleryPost
        fields = '__all__'
        read_only_fields = ('created_at', 'created_by')


class WorkUpdateSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    type_display = serializers.CharField(source='get_post_type_display', read_only=True)

    class Meta:
        model = WorkUpdate
        fields = '__all__'
        read_only_fields = ('created_at', 'created_by')


# ─────────────────────────────────────────────
# SPARES & ACCESSORIES
# ─────────────────────────────────────────────

class InventoryItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryItem
        fields = '__all__'


class AccessorySerializer(serializers.ModelSerializer):
    remaining = serializers.IntegerField(read_only=True)
    sku = serializers.CharField(read_only=True)   # <-- NEW
 
    class Meta:
        model = Accessory
        fields = '__all__'