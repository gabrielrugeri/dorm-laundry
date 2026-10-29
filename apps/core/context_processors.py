from django.conf import settings


def demo_mode(request):
    """`demo_mode` for the banner and the noindex tag in base.html."""
    return {"demo_mode": settings.DEMO_MODE}


def theme(request):
    """The user's light/dark choice for <html data-theme>: saved for a
    logged-in user, otherwise the cookie; "system" follows the phone."""
    from apps.accounts.models import UserPreferences
    from apps.accounts.views import THEME_COOKIE

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        saved = UserPreferences.objects.filter(user=user).values_list("theme", flat=True).first()
        if saved:
            return {"theme": saved}
    return {"theme": request.COOKIES.get(THEME_COOKIE, "system")}


def features(request):
    """Switches for parts of the app that are on hold (see settings)."""
    return {"keys_enabled": settings.KEYS_ENABLED}
