from django.contrib.admin import AdminSite


class SuperuserAdminSite(AdminSite):
    """Django admin (/admin/) for superusers (developers) only.

    Dormitory admins and managers never use it: their screens are /manage/ and
    the key schedule. Anyone else is sent to the admin login page.
    """

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser
