import json
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache 
from django.db.models import F, Sum, ExpressionWrapper, DecimalField, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect 
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django_filters.rest_framework import DjangoFilterBackend
from django.core import signing
from .models import Accessory
from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from .permissions import IsTicketOwnerOrAssignedTech
from django.db.models import Sum
from .models import (
    TechnicianProfile, ServiceType, ServiceRequest,
    ServiceStatusHistory, ServiceDeliveryAsset,
    Category, Product, Payment, Notification,
    GalleryPost, WorkUpdate, Message,
    InventoryItem, Accessory, PartsConsumption
)
from .serializers import (
    TechnicianProfileSerializer, ServiceTypeSerializer, ServiceRequestSerializer,
    ServiceStatusHistorySerializer, ServiceDeliveryAssetSerializer,
    CategorySerializer, ProductSerializer, PaymentSerializer,
    NotificationSerializer, GalleryPostSerializer, WorkUpdateSerializer,
    MessageSerializer,InventoryItemSerializer, AccessorySerializer
)

User = get_user_model()


# ─────────────────────────────────────────────
# NOTIFICATION HELPER FUNCTIONS
# ─────────────────────────────────────────────

def notify_customer_status_update(service_request, new_status):
    """ Direct notification to ticket owner on repair updates """
    if service_request.customer:
        Notification.objects.create(
            recipient=service_request.customer,
            notification_type='STATUS_UPDATE',
            title=f"Repair Update #{service_request.id}",
            message=f"Status changed to: {new_status}",
            related_request=service_request
        )

def notify_assigned_technician(service_request, message_text):
    """ Direct notification to assigned bench operator on incoming chat """
    if service_request.technician:
        Notification.objects.create(
            recipient=service_request.technician,
            notification_type='CUSTOMER_MESSAGE',
            title=f"New Message: Ticket #{service_request.id}",
            message=f"Customer: {message_text[:40]}...",
            related_request=service_request
        )


# ─────────────────────────────────────────────
# PERMISSIONS
# ─────────────────────────────────────────────

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsTechnicianOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        is_tech_bool = getattr(request.user, 'is_technician', False)
        is_staff_bool = getattr(request.user, 'is_staff', False)
        is_superuser_bool = getattr(request.user, 'is_superuser', False)
        user_role_str = str(getattr(request.user, 'role', '')).upper()
        
        if is_tech_bool or is_staff_bool or is_superuser_bool or (user_role_str in ['TECHNICIAN', 'ADMIN']):
            return True
            
        return False


# ─────────────────────────────────────────────
# SERVICE TYPE
# ─────────────────────────────────────────────

class ServiceTypeViewSet(viewsets.ModelViewSet):
    queryset = ServiceType.objects.filter(is_active=True)
    serializer_class = ServiceTypeSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'category']
    ordering_fields = ['name', 'base_price', 'estimated_hours']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [permissions.AllowAny()]


# ─────────────────────────────────────────────
# SERVICE REQUEST VIEWSET & BOOKING
# ─────────────────────────────────────────────

class ServiceRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsTicketOwnerOrAssignedTech]
    serializer_class = ServiceRequestSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'channel', 'priority', 'service_type__category']
    search_fields = ['device_model', 'device_type', 'serial_or_imei', 'customer_notes', 'customer_phone', 'customer_name']
    ordering_fields = ['created_at', 'updated_at', 'priority', 'status']

    def get_queryset(self):
        user = self.request.user

        # 👑 Admin: View all tickets
        if user.is_staff or getattr(user, 'role', None) == 'ADMIN':
            return ServiceRequest.objects.all()

        # 🔧 Technician: View unclaimed pending jobs + jobs assigned to them
        if getattr(user, 'role', None) == 'TECHNICIAN' or getattr(user, 'is_technician', False):
            return ServiceRequest.objects.filter(
                Q(status='PENDING', technician__isnull=True) |
                Q(technician=user)
            ).distinct()

        # 👤 Customer: Strictly limited to their own tickets
        if getattr(user, 'role', None) == 'CUSTOMER':
            return ServiceRequest.objects.filter(customer=user)

        return ServiceRequest.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        role = getattr(user, 'role', None)
 
        if role == 'CUSTOMER':
            # Self-service booking from a logged-in customer
            serializer.save(customer=user, created_by=user)
            return
 
        if role in ('TECHNICIAN', 'ADMIN') or user.is_staff:
            # Reception intake: a staff member is logging a job on behalf
            # of a walk-in / phone customer. customer_id is optional —
            # if the customer has an account, link it; otherwise it's a
            # guest booking identified purely by customer_name/phone.
            customer_id = self.request.data.get('customer_id') or self.request.data.get('customer')
            customer_obj = None
            if customer_id:
                try:
                    customer_obj = User.objects.get(id=customer_id)
                except (User.DoesNotExist, ValueError):
                    customer_obj = None
            serializer.save(customer=customer_obj, created_by=user)
            return
 
        # Fallback (shouldn't normally be hit given permission_classes)
        serializer.save(created_by=user)

    @action(detail=True, methods=['post'], permission_classes=[IsTechnicianOrAdmin])
    def update_status(self, request, pk=None):
        service_request = self.get_object()
        new_status = request.data.get('status')
        note = request.data.get('note', '')

        if new_status not in dict(ServiceRequest.STATUS_CHOICES):
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        service_request.status = new_status
        if new_status == 'COMPLETED':
            service_request.completed_at = timezone.now()
        service_request.save()

        ServiceStatusHistory.objects.create(
            service_request=service_request,
            status=new_status,
            internal_note=note,
            changed_by=request.user
        )

        notify_customer_status_update(service_request, new_status)

        return Response({'message': f'Status updated to {new_status}'})

    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def assign_technician(self, request, pk=None):
        service_request = self.get_object()
        tech_id = request.data.get('technician_id')

        try:
            technician = User.objects.get(id=tech_id)
            service_request.technician = technician
            service_request.status = 'ASSIGNED'
            service_request.internal_status_note = f"Assigned to {technician.get_full_name() or technician.username} by Admin."
            service_request.save()
            
            notify_customer_status_update(service_request, 'ASSIGNED')
            return Response({'message': f'Technician {technician.get_full_name() or technician.username} assigned'})
        except User.DoesNotExist:
            return Response({'error': 'Technician not found'}, status=status.HTTP_404_NOT_FOUND)


class CreatePublicBookingView(generics.CreateAPIView):
    """ Public repair intake view for website bookings (Guest & Registered Users) """
    queryset = ServiceRequest.objects.all()
    serializer_class = ServiceRequestSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        customer_user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(
            customer=customer_user,
            created_by=customer_user if customer_user else None
        )


class ClaimRepairJobView(APIView):
    """ Endpoint allowing technicians to claim unassigned reception requests """
    permission_classes = [IsTechnicianOrAdmin]

    def post(self, request, pk):
        try:
            service_request = ServiceRequest.objects.get(pk=pk)

            if service_request.technician and service_request.technician != request.user:
                claimed_by = service_request.technician.get_full_name() or service_request.technician.username
                return Response(
                    {"error": f"Job already claimed by Technician {claimed_by}."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            service_request.technician = request.user
            service_request.status = 'ASSIGNED'
            tech_name = request.user.get_full_name() or request.user.username
            service_request.internal_status_note = f"Claimed by technician {tech_name}."
            service_request.save()

            ServiceStatusHistory.objects.create(
                service_request=service_request,
                status='ASSIGNED',
                internal_note=f"Job claimed by {tech_name}.",
                changed_by=request.user
            )

            notify_customer_job_claimed(service_request)

            Notification.objects.filter(
                related_request=service_request,
                notification_type='NEW_JOB'
            ).update(
                title=f"Job Taken: {service_request.device_model}",
                message=f"SR-{service_request.id} was claimed by {tech_name}.",
                is_read=True
            )

            return Response({
                "message": f"Job SR-{service_request.id} successfully claimed!",
                "data": ServiceRequestSerializer(service_request).data
            })

        except ServiceRequest.DoesNotExist:
            return Response({"error": "Service request not found."}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────
# CHAT: ACCOUNT-HOLDER MESSAGES (JWT-authenticated)
# ─────────────────────────────────────────────

class ServiceRequestMessagesView(APIView):
    """ Messages for a service request — restricted to ticket owner or assigned tech """
    permission_classes = [IsAuthenticated, IsTicketOwnerOrAssignedTech]

    def _has_access(self, sr, user):
        if user.is_staff or getattr(user, 'role', None) == 'ADMIN':
            return True
        if sr.customer_id and sr.customer_id == user.id:
            return True
        if sr.technician_id and sr.technician_id == user.id:
            return True
        return False

    def get(self, request, pk):
        sr = get_object_or_404(ServiceRequest, pk=pk)
        if not self._has_access(sr, request.user):
            return Response({'error': 'You do not have access to this conversation.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(MessageSerializer(sr.messages.all(), many=True).data)

    def post(self, request, pk):
        sr = get_object_or_404(ServiceRequest, pk=pk)
        if not self._has_access(sr, request.user):
            return Response({'error': 'You do not have access to this conversation.'}, status=status.HTTP_403_FORBIDDEN)

        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'error': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        role = 'TECHNICIAN' if (getattr(request.user, 'role', '') == 'TECHNICIAN' or request.user.is_staff) else 'CUSTOMER'
        msg = Message.objects.create(
            service_request=sr,
            sender_user=request.user,
            sender_role=role,
            sender_display_name=request.user.get_full_name() or request.user.username,
            body=body
        )

        if role == 'CUSTOMER':
            notify_assigned_technician(sr, body)

        return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# CHAT: GUEST ACCESS (Ticket ID + Phone verification)
# ─────────────────────────────────────────────

class VerifyTicketView(APIView):
    """ Guest enters Ticket ID + phone; if it matches, issues a signed, time-limited chat token """
    permission_classes = [AllowAny]

    def post(self, request):
        ticket_id = str(request.data.get('ticket_id', '')).strip()
        phone = str(request.data.get('phone', '')).strip()
        if not ticket_id or not phone:
            return Response({'error': 'Ticket ID and phone are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            sr = ServiceRequest.objects.get(id=ticket_id, customer_phone=phone)
        except ServiceRequest.DoesNotExist:
            return Response({'error': 'No matching ticket for that phone number.'}, status=status.HTTP_404_NOT_FOUND)

        token = signing.dumps({'sr_id': sr.id, 'phone': phone}, salt='ticket-chat-access')
        return Response({
            'token': token,
            'ticket_id': sr.id,
            'status': sr.status,
            'device_model': sr.device_model,
            'technician': sr.technician.get_full_name() if sr.technician else None,
            'technician_phone': getattr(sr.technician, 'phone', None) if sr.technician else None,
        })


class PublicTicketMessagesView(APIView):
    """ Chat for guests: requires a valid signed token from VerifyTicketView """
    permission_classes = [AllowAny]

    def _verify(self, request, pk):
        token = request.headers.get('X-Ticket-Token') or request.data.get('token') or request.query_params.get('token')
        if not token:
            return None
        try:
            data = signing.loads(token, salt='ticket-chat-access', max_age=60 * 60 * 24)
        except signing.BadSignature:
            return None
        return data if str(data.get('sr_id')) == str(pk) else None

    def get(self, request, pk):
        if not self._verify(request, pk):
            return Response({'error': 'Invalid or expired access token.'}, status=status.HTTP_401_UNAUTHORIZED)
        sr = get_object_or_404(ServiceRequest, pk=pk)
        return Response(MessageSerializer(sr.messages.all(), many=True).data)

    def post(self, request, pk):
        data = self._verify(request, pk)
        if not data:
            return Response({'error': 'Invalid or expired access token.'}, status=status.HTTP_401_UNAUTHORIZED)
        sr = get_object_or_404(ServiceRequest, pk=pk)
        body = (request.data.get('body') or '').strip()
        if not body:
            return Response({'error': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        msg = Message.objects.create(
            service_request=sr,
            sender_role='CUSTOMER',
            sender_display_name=sr.customer_name or 'Customer',
            body=body
        )
        notify_assigned_technician(sr, body)
        return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# CATEGORY, PRODUCT & PAYMENTS
# ─────────────────────────────────────────────

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filter_backends = [SearchFilter]
    search_fields = ['name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [permissions.IsAuthenticated()]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_available=True)
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category', 'is_available']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'price', 'stock', 'created_at']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [permissions.IsAuthenticated()]


class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['method', 'status']
    search_fields = ['transaction_ref']
    ordering_fields = ['created_at', 'amount']

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', None) == 'ADMIN' or user.is_staff:
            return Payment.objects.all()
        return Payment.objects.filter(customer=user)

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [permissions.IsAuthenticated()]


# ─────────────────────────────────────────────
# TECHNICIAN PROFILE & NOTIFICATIONS
# ─────────────────────────────────────────────

class TechnicianProfileViewSet(viewsets.ModelViewSet):
    queryset = TechnicianProfile.objects.all()
    serializer_class = TechnicianProfileSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['specialization', 'is_available']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    permission_classes = [IsTechnicianOrAdmin]


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['is_read', 'notification_type']
    ordering_fields = ['created_at']

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'message': 'Notification marked as read'})

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(is_read=True)
        return Response({'message': 'All notifications marked as read'})


# ─────────────────────────────────────────────
# GALLERY & SHOWCASE UPDATES
# ─────────────────────────────────────────────

class GalleryPostViewSet(viewsets.ModelViewSet):
    serializer_class = GalleryPostSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category', 'is_featured']
    search_fields = ['title', 'device_model', 'description']
    ordering_fields = ['created_at']

    def get_queryset(self):
        return GalleryPost.objects.all()

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsTechnicianOrAdmin()]
        return [permissions.AllowAny()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class WorkUpdateViewSet(viewsets.ModelViewSet):
    serializer_class = WorkUpdateSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['post_type', 'is_published']
    search_fields = ['title', 'content']
    ordering_fields = ['created_at']

    def get_queryset(self):
        return WorkUpdate.objects.filter(is_published=True)

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsTechnicianOrAdmin()]
        return [permissions.AllowAny()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ─────────────────────────────────────────────
# REAL-TIME LIVE INVENTORY CONTROL ENGINE
# ─────────────────────────────────────────────
class InventoryItemViewSet(viewsets.ModelViewSet):
    """ Internal repair spares — screens, batteries, chips, ports, etc. """
    queryset = InventoryItem.objects.all().order_by('name')
    serializer_class = InventoryItemSerializer
    authentication_classes = [JWTAuthentication, SessionAuthentication, BasicAuthentication]
    permission_classes = [IsTechnicianOrAdmin]
    lookup_field = 'sku'
 
def sync_accessory_to_spare(accessory):
    """
    Mirrors an Accessory into the Spares Vault (InventoryItem) so it can
    be selected and consumed on repair jobs, using the SAME physical
    stock count. Call this after any create/update on an Accessory that
    has usable_as_spare=True.
    """
    if not accessory.usable_as_spare:
        return
    sku = f"ACC-{accessory.id}"
    InventoryItem.objects.update_or_create(
        sku=sku,
        defaults={
            'name': accessory.name,
            'category': 'ACCESSORY',
            'condition': 'NEW',
            'quantity_on_hand': accessory.remaining,
            'unit_cost': accessory.buy_price,
            'retail_price': accessory.price,
        }
    )

class AccessoryViewSet(viewsets.ModelViewSet):
    """ Showroom-facing accessories sold directly to customers """
    queryset = Accessory.objects.all().order_by('name')
    serializer_class = AccessorySerializer
    authentication_classes = [JWTAuthentication, SessionAuthentication, BasicAuthentication]
    permission_classes = [IsTechnicianOrAdmin]
 
    def perform_create(self, serializer):
        accessory = serializer.save()
        sync_accessory_to_spare(accessory)
 
    def perform_update(self, serializer):
        accessory = serializer.save()
        sync_accessory_to_spare(accessory)
 
    @action(detail=True, methods=['post'], url_path='sell-unit')
    def sell_unit(self, request, pk=None):
        item = self.get_object()
        if item.remaining <= 0:
            return Response({'error': f'{item.name} is out of stock.'}, status=status.HTTP_400_BAD_REQUEST)
        item.quantity_taken += 1
        item.save()
 
        # Keep the mirrored spare (if any) in sync — one unit left the shelf.
        if item.usable_as_spare:
            InventoryItem.objects.filter(sku=f"ACC-{item.id}").update(
                quantity_on_hand=item.remaining
            )
 
        return Response({
            'message': f'Sold 1x {item.name}.',
            'remaining': item.remaining,
            'revenue_this_sale': float(item.price),
        })
    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        item = self.get_object()
        try:
            add_qty = int(request.data.get('quantity', 0))
        except (TypeError, ValueError):
            add_qty = 0
        if add_qty <= 0:
            return Response({'error': 'Quantity must be a positive number.'}, status=status.HTTP_400_BAD_REQUEST)
 
        item.quantity_brought += add_qty
        # Prices can drift between restocks — update them only if provided,
        # so a plain restock doesn't accidentally zero out existing pricing.
        if request.data.get('buy_price') not in (None, ''):
            item.buy_price = request.data['buy_price']
        if request.data.get('price') not in (None, ''):
            item.price = request.data['price']
 
        item.save()
        sync_accessory_to_spare(item)  # keep the mirrored spare's stock in sync too
 
        return Response({
            'message': f'Restocked {add_qty}x {item.name} (SKU {item.sku}).',
            'quantity_brought': item.quantity_brought,
            'remaining': item.remaining,
        })

class InventoryAnalyticsView(APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        items = InventoryItem.objects.all()
        total_units = items.aggregate(Sum('quantity_on_hand'))['quantity_on_hand__sum'] or 0
        
        total_capital = items.aggregate(
            total=Sum(ExpressionWrapper(F('quantity_on_hand') * F('unit_cost'), output_field=DecimalField()))
        )['total'] or 0
        
        projected_revenue = items.aggregate(
            total=Sum(ExpressionWrapper(F('quantity_on_hand') * F('retail_price'), output_field=DecimalField()))
        )['total'] or 0
        
        estimated_profit = projected_revenue - total_capital
        margin_yield = (estimated_profit / projected_revenue * 100) if projected_revenue > 0 else 0
        
        low_stock_items = items.filter(quantity_on_hand__lte=F('min_stock_limit')).values('sku', 'name', 'quantity_on_hand', 'retail_price')

        consumed_total = PartsConsumption.objects.aggregate(
            total=Sum(ExpressionWrapper(F('quantity_used') * F('inventory_item__unit_cost'), output_field=DecimalField()))
        )['total'] or 0
 
        return Response({
            "metrics": {
                "total_inventory_capital": float(total_capital),
                "total_stock_units": total_units,
                "projected_revenue": float(projected_revenue),
                "estimated_gross_profit": float(estimated_profit),
                "margin_yield_percent": round(float(margin_yield), 1),
                "total_spares_consumed_cost": float(consumed_total),   # <-- NEW
            },
            "alerts": list(low_stock_items)
        })


class LogPartConsumptionView(APIView):
    authentication_classes = [JWTAuthentication, SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ticket_id = request.data.get('ticket_id')
        sku = request.data.get('sku')
        quantity = int(request.data.get('quantity', 1))

        repair_ticket = get_object_or_404(ServiceRequest, id=ticket_id)
        inventory_item = get_object_or_404(InventoryItem, sku=sku)

        if inventory_item.quantity_on_hand < quantity:
            return Response(
                {"error": f"Insufficient assets. Only {inventory_item.quantity_on_hand} units available for SKU: {sku}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        consumption = PartsConsumption.objects.create(
            service_request=repair_ticket,
            inventory_item=inventory_item,
            quantity_used=quantity
        )
        if sku.startswith('ACC-'):
            try:
                accessory_id = int(sku.replace('ACC-', ''))
                linked_accessory = Accessory.objects.get(id=accessory_id)
                linked_accessory.quantity_taken += quantity
                linked_accessory.save()
            except (Accessory.DoesNotExist, ValueError):
                pass
            
        return Response({
            "message": f"Successfully allocated {quantity}x {inventory_item.name} to Ticket SR-{ticket_id}.",
            "remaining_stock": inventory_item.quantity_on_hand
        }, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────
# FRONTEND TEMPLATE RENDERING VIEWS
# ─────────────────────────────────────────────

@ensure_csrf_cookie
def market_hub_view(request):
    """ Serves the primary Single Page UI dashboard layer """
    return render(request, 'MKUMBWA_TRONIX/home.html')


@never_cache
def technician_page(request):
    return render(request, "technician.html", {"initial_tab": "dashboard"})


@never_cache
def dashboard_page(request):
    return render(request, "technician.html", {"initial_tab": "dashboard"})


@never_cache
def repairs_queue_page(request):
    """ Sub-view: Detailed repairs queue tracking sheet """
    return render(request, "technician.html", {"initial_tab": "repairs"})


@never_cache
def gallery_upload_page(request):
    """ Sub-view: Workspace media optimization showcase upload bench """
    return render(request, "technician.html", {"initial_tab": "gallery"})


@never_cache
def inventory_page(request):
    """ Dedicated Inventory & Parts Management Dashboard """
    return render(request, "technician.html", {"initial_tab": "inventory"})