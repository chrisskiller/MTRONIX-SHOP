from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
import re
from django.utils.crypto import get_random_string
# ─────────────────────────────────────────────
# NOTIFICATION HELPER HOOK (FUTURE MESSAGING API)
# ─────────────────────────────────────────────

def send_booking_notification(service_request):
    """
    CLEAN HOOK FOR WHATSAPP / SMS API.
    When you are ready to integrate a messaging API (e.g., Beem, WhatsApp Business API):
    Put the API dispatch code HERE.
    This gap is isolated so it won't crash your core logic.
    """
    phone = service_request.customer_phone
    if not phone:
        # If no phone number, we can't send.
        return
        
    job_id = service_request.id
    customer_name = service_request.customer_name or (service_request.customer.first_name if service_request.customer else 'Customer')
    device = service_request.device_model
    
    # Placeholder MESSAGE STRUCTURE for future SMS / WhatsApp
    message = f"Hello {customer_name}, Mkumbwa Tronix has received your request SR-{job_id} for {device}. Track progress at mkumbwatronix.com"
    
    # Until you add API keys, this simply prints to your server console for testing.
    print(f"[{job_id}] - NOTIFICATION QUEUED FOR DISPATCH to {phone}. Message: '{message}'")


def notify_technicians_new_job(service_request):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    technicians = User.objects.filter(role='TECHNICIAN').distinct()
    for tech in technicians:
        Notification.objects.create(
            recipient=tech,
            notification_type='NEW_JOB',
            title=f"New Job: {service_request.device_model}",
            message=f"SR-{service_request.id} — {(service_request.customer_notes or '')[:80]}",
            related_request=service_request,
        )


def notify_customer_job_claimed(service_request):
    technician_name = service_request.technician.get_full_name() or service_request.technician.username
    if service_request.customer:
        Notification.objects.create(
            recipient=service_request.customer,
            notification_type='ASSIGNMENT',
            title="Technician Assigned",
            message=f"{technician_name} is now handling ticket SR-{service_request.id}.",
        )
    phone = service_request.customer_phone
    if phone:
        msg = f"Hi {service_request.customer_name or 'there'}, Ticket SR-{service_request.id} has been claimed by {technician_name}. Track/chat at mkumbwatronix.com"
        print(f"[SR-{service_request.id}] NOTIFICATION QUEUED (claim) to {phone}: '{msg}'")


# ─────────────────────────────────────────────
# TECHNICIAN PROFILE (extends User)
# ─────────────────────────────────────────────

class TechnicianProfile(models.Model):

    SPECIALIZATION_CHOICES = [
        ('HARDWARE', 'Hardware Repair'),
        ('SOFTWARE', 'Software Services'),
        ('BOTH', 'Hardware & Software'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='technician_profile',
        # Assuming you use a custom user model or flags to identify staff
        limit_choices_to={'is_staff': True} 
    )

    employee_id = models.CharField(
        max_length=20,
        unique=True
    )

    specialization = models.CharField(
        max_length=20,
        choices=SPECIALIZATION_CHOICES,
        default='BOTH'
    )

    specialty = models.CharField(
        max_length=100,
        blank=True,
        help_text="Example: Logic Boards, Micro-soldering"
    )

    bio = models.TextField(
        blank=True,
        null=True
    )

    is_available = models.BooleanField(
        default=True,
        help_text="Visible for auto-assignment algorithms"
    )

    is_active_bench = models.BooleanField(
        default=True,
        help_text="Can log into technician workspace dashboard"
    )

    def __str__(self):
        return f"{self.employee_id} • {self.user.get_full_name()}"


# ─────────────────────────────────────────────
# SERVICE CATALOG
# ─────────────────────────────────────────────

class ServiceType(models.Model):
    CATEGORY_CHOICES = [
        ('HARDWARE', 'Hardware Repair (Phone/Laptop/Gaming)'),
        ('SOFTWARE', 'Software Service (OS/App Installation)'),
        ('DIGITAL', 'Digital Delivery (Licenses/Data Recovery)'),
    ]

    name = models.CharField(max_length=150, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    estimated_hours = models.PositiveIntegerField(help_text="Estimated hours to complete")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} [{self.get_category_display()}]"


# ─────────────────────────────────────────────
# UNIFIED SERVICE REQUEST (CORE ENGINE)
# ─────────────────────────────────────────────

class ServiceRequest(models.Model):

    STATUS_CHOICES = [
        ('PENDING', 'Pending Assessment'),
        ('ASSIGNED', 'Assigned'), # NEW
        ('PROCESSING', 'In Progress / Repairing'),
        ('AWAITING_PARTS', 'Awaiting Spare Parts'),
        ('TESTING', 'Quality Control Testing'),
        ('READY', 'Ready for Pickup / Delivery'),
        ('COMPLETED', 'Completed & Closed'),
        ('CANCELLED', 'Cancelled'),
    ]

    CHANNEL_CHOICES = [
        ('WALK_IN', 'Walk-in (Direct Office Visit)'),
        ('REMOTE', 'Remote (Online Service Only)'),
        ('ONLINE_TO_PHYSICAL', 'Online Booking → Office Visit'),
    ]

    PRIORITY_CHOICES = [
        ('NORMAL', 'Normal'),
        ('URGENT', 'Urgent'),
        ('EMERGENCY', 'Emergency'),
    ]

    # Parties involved (UPDATED)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Essential: don't delete request if user is deleted
        null=True,
        blank=True,
        related_name='customer_requests',
        limit_choices_to={'role': 'CUSTOMER'}
    )
    
    # Intake details for Guest / UNASSIGNED reception flow
    customer_name = models.CharField(max_length=100, blank=True, null=True, help_text="Used for Guest bookings")
    customer_phone = models.CharField(max_length=20, help_text="Essential for future SMS/WhatsApp")

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Critical for 'Claim Job' flow
        null=True,
        blank=True,
        related_name='assigned_tasks',
        limit_choices_to={'is_staff': True} # Change this to your tech flag if needed
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True, # Critical for ONLINE self-bookings
        related_name='created_requests',
        help_text="Staff member who created this ticket (for walk-ins)"
    )

    # Service info
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, null=True, blank=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='WALK_IN')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='NORMAL')

    # Device info
    device_type = models.CharField(max_length=100, help_text="e.g., Phone, Laptop, PS5, PC")
    device_model = models.CharField(max_length=150, help_text="e.g., iPhone 13, Dell XPS 13, PS5 Slim")
    serial_or_imei = models.CharField(max_length=100, blank=True, null=True)

    # Notes
    customer_notes = models.TextField(help_text="Customer description of the fault or requirement")
    tech_diagnostic_notes = models.TextField(blank=True, null=True, help_text="Internal notes by the technician")

    # Pricing
    quoted_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Price quoted to customer after assessment"
    )
    final_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Final charge after job completion"
    )

    # Status & timestamps (UPDATED)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    # Use for activity logs when CLAIMING or CHANGING status internally
    internal_status_note = models.CharField(max_length=255, blank=True, null=True, help_text="Simple log: E.g., Job Claimed by Tech Rashid.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        # Professional dynamic string representation showing CLAIM state
        assigned_name = self.technician.first_name if self.technician else "UNASSIGNED (Reception Pool)"
        return f"SR-{self.id} | {self.device_model} | {self.customer_phone} | {self.status} (Tech: {assigned_name})"
    
    def save(self, *args, **kwargs):
        # professional safe hook trigger on creation
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            # When the request is first created, queue the notification hook
            send_booking_notification(self)
            notify_technicians_new_job(self)


# ─────────────────────────────────────────────
# SERVICE WORKFLOW TRACKING
# ─────────────────────────────────────────────

class ServiceStatusHistory(models.Model):
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='status_history'
    )
    status = models.CharField(max_length=20, choices=ServiceRequest.STATUS_CHOICES)
    internal_note = models.TextField(blank=True, null=True, help_text="Why was the status changed?")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Service Status Histories"
        ordering = ['-timestamp']

    def __str__(self):
        return f"SR-{self.service_request.id} → {self.status} at {self.timestamp}"


# ─────────────────────────────────────────────
# DIGITAL ASSET DELIVERY
# ─────────────────────────────────────────────

class ServiceDeliveryAsset(models.Model):
    service_request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='digital_delivery'
    )
    license_key_or_text = models.TextField(
        blank=True, null=True,
        help_text="Digital licenses, activation strings, or access codes"
    )
    secure_delivery_file = models.FileField(
        upload_to='digital_deliveries/',
        blank=True, null=True,
        help_text="Recovered data files, reports, or installers"
    )
    delivery_notes = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Delivery Asset for SR-{self.service_request.id}"


# ─────────────────────────────────────────────
# ACCESSORIES / PRODUCTS
# ─────────────────────────────────────────────

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} | TZS {self.price} | Stock: {self.stock}"

    @property
    def in_stock(self):
        return self.stock > 0


# ─────────────────────────────────────────────
# PAYMENTS
# ─────────────────────────────────────────────

class Payment(models.Model):
    METHOD_CHOICES = [
        ('MPESA', 'M-Pesa'),
        ('CASH', 'Cash'),
        ('PAYPAL', 'PayPal'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name='payments',
        null=True, blank=True
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    transaction_ref = models.CharField(
        max_length=200, blank=True, null=True,
        help_text="M-Pesa transaction ID or PayPal reference"
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment | {self.customer.username} | {self.method} | TZS {self.amount} | {self.status}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('STATUS_UPDATE', 'Service Status Update'),
        ('ASSIGNMENT', 'Technician Assigned'),
        ('PAYMENT', 'Payment Confirmed'),
        ('GENERAL', 'General Notice'),
        ('NEW_JOB', 'New Job Available'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    related_request = models.ForeignKey(
        'ServiceRequest',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='notifications',
        help_text="The job this notification is about, if any (used to sync 'claimed' state across all technicians)"
    )
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.username} | {self.title} | {'Read' if self.is_read else 'Unread'}"


# ─────────────────────────────────────────────
# GALLERY / PORTFOLIO
# ─────────────────────────────────────────────

class GalleryPost(models.Model):
    CATEGORY_CHOICES = [
        ('PHONE', 'Phone Repair'),
        ('LAPTOP', 'Laptop Repair'),
        ('CONSOLE', 'Gaming Console'),
        ('SOFTWARE', 'Software Service'),
        ('OTHER', 'Other'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True, null=True)
    before_image = models.ImageField(upload_to='gallery/before/', blank=True, null=True)
    after_image = models.ImageField(upload_to='gallery/after/', blank=True, null=True)
    device_model = models.CharField(max_length=150, blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} [{self.category}]"


# ─────────────────────────────────────────────
# WORK UPDATES / POSTS
# ─────────────────────────────────────────────

class WorkUpdate(models.Model):
    TYPE_CHOICES = [
        ('COMPLETED_JOB', 'Completed Job'),
        ('TIP', 'Tech Tip'),
        ('NEWS', 'News & Updates'),
        ('PROMO', 'Promotion'),
    ]

    title = models.CharField(max_length=200)
    post_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    content = models.TextField()
    image = models.ImageField(upload_to='posts/', blank=True, null=True)
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} [{self.post_type}]"


class InventoryItem(models.Model):
    CATEGORY_CHOICES = [
        ('SCREEN', 'Screens & Displays'),
        ('BATTERY', 'Batteries'),
        ('CHIP', 'Microchips & ICs'),
        ('PORT', 'Charging & HDMI Ports'),
        ('ACCESSORY', 'Mirrored from Accessories'),
        ('OTHER', 'Other Component Hardware'),
    ]

    CONDITION_CHOICES = [
        ('NEW', 'Brand New'),
        ('USED', 'Used / Extracted'),
        ('REFURB', 'Refurbished'),
    ]
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='NEW')

    sku = models.CharField(max_length=50, unique=True, primary_key=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    quantity_on_hand = models.IntegerField(validators=[MinValueValidator(0)])
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    retail_price = models.DecimalField(max_digits=10, decimal_places=2)
    min_stock_limit = models.IntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sku} - {self.name}"


class PartsConsumption(models.Model):
    service_request = models.ForeignKey('ServiceRequest', on_delete=models.CASCADE, related_name='parts_used')
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name='consumptions')
    quantity_used = models.PositiveIntegerField(default=1)
    date_consumed = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Automatically deduct stock when a technician logs part consumption
        if not self.pk: # Only on creation
            item = self.inventory_item
            item.quantity_on_hand -= self.quantity_used
            item.save()
        super().save(*args, **kwargs)


class Message(models.Model):
    SENDER_ROLE_CHOICES = [('CUSTOMER', 'Customer'), ('TECHNICIAN', 'Technician')]

    service_request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name='messages')
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_messages')
    sender_role = models.CharField(max_length=20, choices=SENDER_ROLE_CHOICES)
    sender_display_name = models.CharField(max_length=100, blank=True, help_text="Used when sender has no account (guest)")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Msg on SR-{self.service_request_id} by {self.sender_role}"




# ─────────────────────────────────────────────────────────────
def generate_accessory_sku(name):
    """
    Professional, human-readable, collision-checked SKU generator.
    Format: ACC-<first 6 alnum chars of the name, uppercased>-<4 random chars>
    e.g. "65W GaN Charger" -> ACC-65WGAN-K7X2
 
    The random suffix uses a character set with no 0/O or 1/I, so a SKU
    printed on a sticker can never be misread. Guaranteed unique via a
    database check-and-retry loop (collisions are astronomically rare
    at 4 chars from a 32-symbol alphabet, but we never trust luck alone).
    """
    base = re.sub(r'[^A-Z0-9]', '', name.upper())[:6] or 'ACC'
    prefix = f"ACC-{base}"
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I
    while True:
        candidate = f"{prefix}-{get_random_string(4, allowed_chars=alphabet)}"
        if not Accessory.objects.filter(sku=candidate).exists():
            return candidate
# ─────────────────────────────────────────────────────────────

class Accessory(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40, unique=True, blank=True, null=True)   # <-- NEW, auto-generated
    quantity_brought = models.PositiveIntegerField(default=0)
    quantity_taken = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    usable_as_spare = models.BooleanField(default=False, help_text="If true, this item is also mirrored into the Spares Vault for use on repair jobs")
    created_at = models.DateTimeField(auto_now_add=True)
 
    @property
    def remaining(self):
        return self.quantity_brought - self.quantity_taken
 
    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = generate_accessory_sku(self.name)
        super().save(*args, **kwargs)
 
    def __str__(self):
        return f"{self.sku} — {self.name} ({self.remaining} left)"
 