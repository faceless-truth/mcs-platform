"""MCS Platform - Core URL Configuration"""
from django.urls import path
from . import views
from . import views_audit

app_name = "core"

urlpatterns = [

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
    path("years/<uuid:pk>/trial-balance/pdf/", views.trial_balance_pdf, name="trial_balance_pdf"),

    # Account Mapping
    path("mapping/", views.account_mapping_list, name="account_mapping_list"),
    path("mapping/create/", views.account_mapping_create, name="account_mapping_create"),
    path("years/<uuid:pk>/map-accounts/", views.map_client_accounts, name="map_client_accounts"),

    # Journal Entries
    path("years/<uuid:pk>/adjustments/", views.adjustment_list, name="adjustment_list"),
    path("years/<uuid:pk>/adjustments/create/", views.adjustment_create, name="adjustment_create"),
    path("journals/<uuid:pk>/", views.journal_detail, name="journal_detail"),
    path("journals/<uuid:pk>/post/", views.journal_post, name="journal_post"),
    path("journals/<uuid:pk>/delete/", views.journal_delete, name="journal_delete"),
    path("years/<uuid:pk>/accounts-api/", views.account_list_api, name="account_list_api"),
    path("years/<uuid:pk>/journals/pdf/", views.journals_pdf, name="journals_pdf"),

    # Financial Statements Preview
    path("years/<uuid:pk>/statements/", views.financial_statements_view, name="financial_statements_view"),

    # Document Generation
    path("years/<uuid:pk>/generate/", views.generate_document, name="generate_document"),

    # Entity Officers / Signatories
    path("entities/<uuid:pk>/officers/", views.entity_officers, name="entity_officers"),
    path("entities/<uuid:entity_pk>/officers/create/", views.entity_officer_create, name="entity_officer_create"),
    path("officers/<uuid:pk>/edit/", views.entity_officer_edit, name="entity_officer_edit"),
    path("officers/<uuid:pk>/delete/", views.entity_officer_delete, name="entity_officer_delete"),

    # Access Ledger Import
    path("import/access-ledger/", views.access_ledger_import, name="access_ledger_import"),

    # Chart of Accounts
    path("chart-of-accounts/", views_audit.chart_of_accounts, name="chart_of_accounts"),

    # Audit Library
    path("audit-library/", views_audit.audit_library, name="audit_library"),

    # Risk Flags
    path("years/<uuid:pk>/risk-flags/", views_audit.risk_flags_view, name="risk_flags"),
    path("risk-flags/<uuid:pk>/resolve/", views_audit.resolve_risk_flag, name="resolve_risk_flag"),

    # HTMX partials
    path("htmx/client-search/", views.htmx_client_search, name="htmx_client_search"),
    path("htmx/tb-line/<uuid:pk>/map/", views.htmx_map_tb_line, name="htmx_map_tb_line"),
]
