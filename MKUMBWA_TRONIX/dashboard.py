from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from .models import ServiceRequest, Product, Payment, Notification
from django.contrib.auth import get_user_model

User = get_user_model()


class DashboardStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now()
        last_30_days = today - timedelta(days=30)

        # Admin sees everything, technician sees their own
        if user.role == 'ADMIN':
            requests_qs = ServiceRequest.objects.all()
        elif user.role == 'TECHNICIAN':
            requests_qs = ServiceRequest.objects.filter(technician=user)
        else:
            requests_qs = ServiceRequest.objects.filter(customer=user)

        # Service request stats
        total_requests = requests_qs.count()
        pending = requests_qs.filter(status='PENDING').count()
        processing = requests_qs.filter(status='PROCESSING').count()
        completed = requests_qs.filter(status='COMPLETED').count()
        cancelled = requests_qs.filter(status='CANCELLED').count()
        new_this_month = requests_qs.filter(created_at__gte=last_30_days).count()

        # Revenue stats (admin only)
        revenue_data = {}
        if user.role == 'ADMIN':
            total_revenue = Payment.objects.filter(
                status='CONFIRMED'
            ).aggregate(total=Sum('amount'))['total'] or 0

            monthly_revenue = Payment.objects.filter(
                status='CONFIRMED',
                created_at__gte=last_30_days
            ).aggregate(total=Sum('amount'))['total'] or 0

            revenue_data = {
                'total_revenue': total_revenue,
                'monthly_revenue': monthly_revenue,
            }

        # Product stats (admin only)
        product_data = {}
        if user.role == 'ADMIN':
            total_products = Product.objects.count()
            low_stock = Product.objects.filter(stock__lte=5, is_available=True).count()
            out_of_stock = Product.objects.filter(stock=0).count()

            product_data = {
                'total_products': total_products,
                'low_stock_products': low_stock,
                'out_of_stock_products': out_of_stock,
            }

        # User stats (admin only)
        user_data = {}
        if user.role == 'ADMIN':
            total_customers = User.objects.filter(role='CUSTOMER').count()
            total_technicians = User.objects.filter(role='TECHNICIAN').count()

            user_data = {
                'total_customers': total_customers,
                'total_technicians': total_technicians,
            }

        # Unread notifications
        unread_notifications = Notification.objects.filter(
            recipient=user,
            is_read=False
        ).count()

        return Response({
            'service_requests': {
                'total': total_requests,
                'pending': pending,
                'processing': processing,
                'completed': completed,
                'cancelled': cancelled,
                'new_this_month': new_this_month,
            },
            **revenue_data,
            **product_data,
            **user_data,
            'unread_notifications': unread_notifications,
        })