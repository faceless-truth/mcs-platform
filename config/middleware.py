"""
Custom middleware for security enforcement.
"""
from django.shortcuts import redirect
from django.urls import reverse


class Require2FAMiddleware:
    """
    Middleware that enforces 2FA setup for all authenticated users.
    Users without 2FA configured are redirected to the 2FA setup page.
    """

    EXEMPT_URLS = [
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/totp-verify/",
        "/accounts/setup-2fa/",
        "/admin/",
        "/static/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.has_2fa:
            # Allow exempt URLs
            path = request.path
            if not any(path.startswith(url) for url in self.EXEMPT_URLS):
                # Allow signup URLs (they include token)
                if "/accounts/signup/" not in path:
                    return redirect(reverse("accounts:setup_2fa"))

        return self.get_response(request)
