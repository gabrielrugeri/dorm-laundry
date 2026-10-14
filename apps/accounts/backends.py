from django.conf import settings
from django.contrib.auth.backends import ModelBackend

from .models import Resident, User


class ResidentBackend(ModelBackend):
    """Log a resident in with their student code and PIN.

    The PIN is the user's password (stored hashed). The dormitory comes from
    the DEFAULT_DORMITORY_SLUG setting while the pilot has a single dormitory.

    Unknown codes cost the same time as wrong PINs (a dummy hash is computed),
    so response timing does not reveal whether a student code exists.
    Staff (managers, admins) log in with their username through ModelBackend.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            resident = Resident.objects.select_related("user").get(
                dormitory__slug=settings.DEFAULT_DORMITORY_SLUG,
                student_code=username.strip(),
            )
        except Resident.DoesNotExist:
            User().set_password(password)
            return None
        user = resident.user
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
