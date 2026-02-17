"""MCS Platform URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    # Review app handles the dashboard (homepage) and review pages
    path("", include("review.urls")),
    # Core app handles clients, entities, financial years, etc.
    path("", include("core.urls")),
    # Integrations app handles Xero/MYOB/QB connections and cloud imports
    path("integrations/", include("integrations.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Customise admin site
admin.site.site_header = "MCS Financial Statements"
admin.site.site_title = "MCS Admin"
admin.site.index_title = "Administration"
