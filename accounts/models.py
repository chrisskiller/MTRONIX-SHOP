from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    ROLE_CHOICES = [
        ('CUSTOMER', 'Customer'),
        ('TECHNICIAN', 'Technician'),
        ('ADMIN', 'Admin'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='CUSTOMER')
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_photo = models.ImageField(upload_to='profiles/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_admin(self):
        return self.role == 'ADMIN'

    def is_technician(self):
        return self.role == 'TECHNICIAN'

    def is_customer(self):
        return self.role == 'CUSTOMER'

    def __str__(self):
        return f"{self.get_full_name()} [{self.role}] - {self.username}"