from . import roles


def _identity(user):
    """Who is logged in, for the header: "Name · room" for a resident, "Name ·
    Dormitory" for staff. Names are shown exactly as stored, never split or
    shortened here (the template cuts long ones off with an ellipsis)."""
    resident = getattr(user, "resident", None)
    if resident is not None:
        return f"{resident.full_name} · {resident.room}" if resident.room else resident.full_name
    name = user.get_full_name() or user.get_username()
    profile = getattr(user, "staff_profile", None)
    return f"{name} · {profile.dormitory.name}" if profile is not None else name


def user_roles(request):
    """`is_admin_role` for the navigation (link to /manage/) and `identity`
    for the header. Residents only ever see their own name and room."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    return {"is_admin_role": roles.has_role(user, roles.ADMIN), "identity": _identity(user)}
