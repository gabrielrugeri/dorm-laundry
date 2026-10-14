"""View decorators that check roles and scope the request to a dormitory.

    @resident_required
    def my_bookings(request):
        request.dormitory  # the logged-in resident's dormitory

    @role_required(roles.MANAGER, roles.ADMIN)
    def key_schedule(request): ...

Anonymous users are sent to the login page. Logged-in users without one of the
roles (or without a dormitory) get 403 Forbidden. Pages render in the
dormitory's timezone.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from . import roles


def get_user_dormitory(user):
    """The dormitory a user belongs to: a resident's, or a staff member's."""
    for profile_name in ("resident", "staff_profile"):
        profile = getattr(user, profile_name, None)
        if profile is not None:
            return profile.dormitory
    return None


def is_staff_member(user):
    return roles.has_role(user, roles.MANAGER) or roles.has_role(user, roles.ADMIN)


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not any(roles.has_role(request.user, role) for role in allowed_roles):
                raise PermissionDenied
            dormitory = get_user_dormitory(request.user)
            if dormitory is None:
                raise PermissionDenied
            request.dormitory = dormitory
            # Show every date and time on the page in the dormitory's timezone.
            with timezone.override(dormitory.tzinfo):
                return view(request, *args, **kwargs)

        return login_required(wrapper)

    return decorator


resident_required = role_required(roles.RESIDENT)
staff_required = role_required(roles.MANAGER, roles.ADMIN)
