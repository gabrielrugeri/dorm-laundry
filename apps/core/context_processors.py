from django.conf import settings


def demo_mode(request):
    """`demo_mode` for the banner and the noindex tag in base.html."""
    return {"demo_mode": settings.DEMO_MODE}
