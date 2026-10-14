from .models import LedgerEntry


def resident_balance(request):
    """`resident_balance` for the navigation bar; only for logged-in residents."""
    user = getattr(request, "user", None)
    resident = getattr(user, "resident", None) if user and user.is_authenticated else None
    if resident is None:
        return {}
    return {"resident_balance": LedgerEntry.objects.balance(resident)}
