from django.conf import settings


def demo_mode(request):
    """`demo_mode` for the banner and the noindex tag in base.html."""
    return {"demo_mode": settings.DEMO_MODE}


def features(request):
    """Switches for parts of the app that are on hold (see settings)."""
    return {"keys_enabled": settings.KEYS_ENABLED}
