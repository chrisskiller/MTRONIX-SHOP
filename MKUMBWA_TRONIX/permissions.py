from rest_framework import permissions

class IsTicketOwnerOrAssignedTech(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_staff or user.role == 'ADMIN':
            return True

        if user.role == 'CUSTOMER':
            return obj.customer == user

        if user.role == 'TECHNICIAN':
            return obj.technician is None or obj.technician == user

        return False