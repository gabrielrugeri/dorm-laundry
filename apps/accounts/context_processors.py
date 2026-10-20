from . import roles


def user_roles(request):
    """`is_admin_role` for the navigation (link to /manage/)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    return {"is_admin_role": roles.has_role(user, roles.ADMIN)}
