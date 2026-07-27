from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .dashboard import DashboardStatsView

# Using DefaultRouter for standard CRUD ViewSets
router = DefaultRouter()
router.register(r'services', views.ServiceTypeViewSet, basename='service-type')
router.register(r'requests', views.ServiceRequestViewSet, basename='service-request')
router.register(r'categories', views.CategoryViewSet, basename='category')
router.register(r'products', views.ProductViewSet, basename='product')
router.register(r'payments', views.PaymentViewSet, basename='payment')
router.register(r'technicians', views.TechnicianProfileViewSet, basename='technician')
router.register(r'notifications', views.NotificationViewSet, basename='notification')
router.register(r'gallery', views.GalleryPostViewSet, basename='gallery')
router.register(r'updates', views.WorkUpdateViewSet, basename='updates')
router.register(r'inventory/spares', views.InventoryItemViewSet, basename='inventory-spares')
router.register(r'inventory/accessories', views.AccessoryViewSet, basename='inventory-accessories')

urlpatterns = [
    # Router URLs handle standard viewsets (like /requests/, /products/, etc.)
    path('', include(router.urls)),
    
    # Standard Dashboard Stats
    path('dashboard-stats/', DashboardStatsView.as_view(), name='dashboard-stats'),
    
    # ─────────────────────────────────────────────
    # TECHNICIAN WORKFLOW ENDPOINTS (NEW)
    # ─────────────────────────────────────────────
    
    # Dedicated endpoint for a technician to claim an unassigned request.
    # This maps to the dedicated view needed for the frontend JS to call.
    path('tech/claim-job/<int:pk>/', views.ClaimRepairJobView.as_view(), name='tech-claim-job'),
    path('public/book/', views.CreatePublicBookingView.as_view(), name='public-booking'),
    path('service-requests/<int:pk>/messages/', views.ServiceRequestMessagesView.as_view(), name='sr-messages'),
    path('public/verify-ticket/', views.VerifyTicketView.as_view(), name='verify-ticket'),
    path('public/ticket/<int:pk>/messages/', views.PublicTicketMessagesView.as_view(), name='public-ticket-messages'),
    ]