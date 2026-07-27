from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework_simplejwt.views import TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

# Import the authenticators and protected view controllers
from accounts.views import CustomTokenObtainPairView
from MKUMBWA_TRONIX.views import (
    technician_page, 
    dashboard_page, 
    repairs_queue_page, 
    gallery_upload_page,
    inventory_page,
    LogPartConsumptionView, 
    InventoryAnalyticsView
)

urlpatterns = [
    # Primary Application Entry Point
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('admin/', admin.site.urls),
    
    # Authentication Endpoints
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # App API Modular Routes
    path('api/accounts/', include('accounts.urls')),
    path('api/', include('MKUMBWA_TRONIX.urls')),
    
    # Frontend Pages & Portals
    path('technician/', technician_page, name='technician_page'),
    path('dashboard/', dashboard_page, name='dashboard_analytics_page'),
    path('repairs-queue/', repairs_queue_page, name='repairs_queue'),
    path('gallery-upload/', gallery_upload_page, name='gallery_upload'),
    path('customer/', TemplateView.as_view(template_name='customer.html'), name='customer_portal'),
    path('inventory/', inventory_page, name='inventory_dashboard'),
    
    # Direct Engine API Overrides
    path('api/inventory/analytics/', InventoryAnalyticsView.as_view(), name='inventory-analytics'),
    path('api/inventory/consume/', LogPartConsumptionView.as_view(), name='inventory-consume'),
]

# Serve Uploaded Media Files during Development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)