"""Integrations URL Configuration"""
from django.urls import path
from . import views

app_name = "integrations"

urlpatterns = [
    # Connection management
    path(
        "entities/<uuid:entity_pk>/connections/",
        views.connection_manage,
        name="connection_manage",
    ),
    path(
        "entities/<uuid:entity_pk>/connect/<str:provider_name>/",
        views.oauth_connect,
        name="oauth_connect",
    ),
    path("oauth/callback/", views.oauth_callback, name="oauth_callback"),
    path(
        "entities/<uuid:entity_pk>/select-tenant/",
        views.select_tenant,
        name="select_tenant",
    ),
    path(
        "connections/<uuid:connection_pk>/disconnect/",
        views.disconnect,
        name="disconnect",
    ),

    # Cloud import with review/approval
    path(
        "years/<uuid:fy_pk>/import-cloud/",
        views.import_from_cloud,
        name="import_from_cloud",
    ),
    path(
        "years/<uuid:fy_pk>/review-import/",
        views.review_import,
        name="review_import",
    ),
    path(
        "years/<uuid:fy_pk>/commit-import/",
        views.commit_import,
        name="commit_import",
    ),
]
