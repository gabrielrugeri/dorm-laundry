"""Small security middlewares, provider-neutral (they work behind nginx,
Railway or any other proxy)."""

from django.conf import settings
from django.http import HttpResponse

# Pages may load only from our own origin (docs/CLAUDE.md hard rule 1): the
# browser itself refuses anything from another domain. No inline scripts; all
# JavaScript lives in static files.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        # The installable app: manifest and service worker from our own server.
        "manifest-src 'self'",
        "worker-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)
# Django's own admin (/admin/, superusers only) uses inline style attributes.
ADMIN_CSP = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")


class RequestSizeLimitMiddleware:
    """Refuse request bodies above MAX_UPLOAD_BYTES_HARD before Django reads
    them. The web server (nginx `client_max_body_size`) uses the same value."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.MAX_UPLOAD_BYTES_HARD:
            return HttpResponse("Request too large", status=413, content_type="text/plain")
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Content-Security-Policy on every response, and in demo mode a header
    telling search engines not to index anything."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            admin = request.path.startswith("/admin/")
            response["Content-Security-Policy"] = ADMIN_CSP if admin else CSP
        if settings.DEMO_MODE:
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response
