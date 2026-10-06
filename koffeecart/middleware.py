from django.urls import reverse

# Content-Security-Policy: the browser only runs scripts, styles, fonts and images that come
# from this site. An attacker who manages to inject HTML (a stored XSS in a review, say) still
# cannot run inline <script> or load code from elsewhere.
CSP = '; '.join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
])
# The Django admin (and the thumbnails in it) still use style="..." attributes.
ADMIN_CSP = CSP.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")

PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), payment=()'


class SecurityHeadersMiddleware:
    """Adds CSP and Permissions-Policy to every response that does not set its own."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        is_admin = request.path.startswith(reverse('admin:index'))
        response.headers.setdefault('Content-Security-Policy', ADMIN_CSP if is_admin else CSP)
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        return response
