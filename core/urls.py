"""MCS Platform - Core URL Configuration"""
from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Clients
    path("clients/", views.client_list, name="client_list"),
    path("clients/create/", views.client_create, name="client_create"),
    path("clients/<uuid:pk>/", views.client_detail, name="client_detail"),
    path("clients/<uuid:pk>/edit/", views.client_edit, name="client_edit"),

    # Entities
    path("clients/<uuid:client_pk>/entities/create/", views.entity_create, name="entity_create"),
    path("entities/<uuid:pk>/", views.entity_detail, name="entity_detail"),
    path("entities/<uuid:pk>/edit/", views.entity_edit, name="entity_edit"),

    # Financial Years
    path("entities/<uuid:entity_pk>/years/create/", views.financial_year_create, name="financial_year_create"),
    path("years/<uuid:pk>/", views.financial_year_detail, name="financial_year_detail"),
    path("years/<uuid:pk>/status/", views.financial_year_status, name="financial_year_status"),
    path("years/<uuid:pk>/roll-forward/", views.roll_forward, name="roll_forward"),

    # Trial Balance
    path("years/<uuid:pk>/import/", views.trial_balance_import, name="trial_balance_import"),
    path("years/<uuid:pk>/trial-balance/", views.trial_balance_view, name="trial_balance_view"),

    # Account Mapping
    path("mapping/", views.account_mapping_list, name="account_mapping_list"),
    path("mapping/create/", views.account_mapping_create, name="account_mapping_create"),
    path("years/<uuid:pk>/map-accounts/", views.map_client_accounts, name="map_client_accounts"),

    # Adjusting Journals
    path("years/<uuid:pk>/adjustments/", views.adjustment_list, name="adjustment_list"),
    path("years/<uuid:pk>/adjustments/create/", views.adjustment_create, name="adjustment_create"),

    # Financial Statements Preview
    path("years/<uuid:pk>/statements/", views.financial_statements_view, name="financial_statements_view"),

    # Document Generation
    path("years/<uuid:pk>/generate/", views.generate_document, name="generate_document"),

    # HTMX partials
    path("htmx/client-search/", views.htmx_client_search, name="htmx_client_search"),
    path("htmx/tb-line/<uuid:pk>/map/", views.htmx_map_tb_line, name="htmx_map_tb_line"),
]
