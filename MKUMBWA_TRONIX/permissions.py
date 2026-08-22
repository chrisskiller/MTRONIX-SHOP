from rest_framework import permissions

class IsTicketOwnerOrAssignedTech(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_staff or user.role == 'ADMIN':
            return True

        if user.role == 'CUSTOMER':
            return obj.customer == user

        if user.role == 'TECHNICIAN':
            # Shop-wide management model: any technician can view and update
            # any ticket that has come into the office, not only ones
            # unclaimed or assigned to them — matches the widened
            # ServiceRequestViewSet.get_queryset() visibility.
            return True

        return False