from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .models import ServiceRequest, ServiceStatusHistory, Notification


# ─────────────────────────────────────────────
# TRACK OLD STATUS BEFORE SAVE
# ─────────────────────────────────────────────

@receiver(pre_save, sender=ServiceRequest)
def capture_old_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = ServiceRequest.objects.get(pk=instance.pk)
            instance._old_status = old.status
            instance._old_technician = old.technician
        except ServiceRequest.DoesNotExist:
            instance._old_status = None
            instance._old_technician = None
    else:
        instance._old_status = None
        instance._old_technician = None


# ─────────────────────────────────────────────
# AUTO RECORD STATUS HISTORY + NOTIFICATIONS
# ─────────────────────────────────────────────

@receiver(post_save, sender=ServiceRequest)
def record_status_history(sender, instance, created, **kwargs):
    if created:
        ServiceStatusHistory.objects.create(
            service_request=instance,
            status=instance.status,
            internal_note='Service request created',
            changed_by=instance.created_by
        )
        # Notify customer — only if this ticket is linked to a real account.
        # Guest / walk-in bookings (customer=None) have nowhere to deliver
        # a Notification, since `recipient` is a required field.
        if instance.customer:
            Notification.objects.create(
                recipient=instance.customer,
                notification_type='STATUS_UPDATE',
                title='Service Request Received',
                message=f'Your service request for {instance.device_model} has been received and is pending assessment.'
            )
    else:
        old_status = getattr(instance, '_old_status', None)
        old_technician = getattr(instance, '_old_technician', None)

        # Status changed
        if old_status and old_status != instance.status:
            ServiceStatusHistory.objects.create(
                service_request=instance,
                status=instance.status,
                internal_note=f'Status changed from {old_status} to {instance.status}',
                changed_by=instance.created_by
            )
            # Notify customer of status change (guarded — see note above)
            if instance.customer:
                Notification.objects.create(
                    recipient=instance.customer,
                    notification_type='STATUS_UPDATE',
                    title='Service Update',
                    message=f'Your {instance.device_model} service status has been updated to: {instance.get_status_display()}'
                )

        # Technician assigned
        if instance.technician and old_technician != instance.technician:
            if instance.customer:
                Notification.objects.create(
                    recipient=instance.customer,
                    notification_type='ASSIGNMENT',
                    title='Technician Assigned',
                    message=f'A technician has been assigned to your {instance.device_model} service request.'
                )

        # Auto set completed_at
        if instance.status == 'COMPLETED' and not instance.completed_at:
            ServiceRequest.objects.filter(pk=instance.pk).update(
                completed_at=timezone.now()
            )