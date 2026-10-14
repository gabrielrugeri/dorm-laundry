"""User roles. Each role is a Django group, created by a data migration.

- resident: books machines, sees only their own data
- manager: hands out keys; sees today's schedule with names and rooms
- admin: manages residents, credits balances, sees everything in their dormitory
"""

RESIDENT = "resident"
MANAGER = "manager"
ADMIN = "admin"

ALL_ROLES = [RESIDENT, MANAGER, ADMIN]


def has_role(user, role):
    """True if the user is active and in the given role's group."""
    if not user.is_authenticated or not user.is_active:
        return False
    return user.groups.filter(name=role).exists()
