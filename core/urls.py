"""MCS Platform - Core URL Configuration"""
from django.urls import path
from . import views
from . import views_audit

app_name = "core"

urlpatterns = [

    # Entities (top-level — replaces old Clients)
    path("entities/", views.entity_list, name="entity_list"),
    path("entities/create/", views.entity_create, name="entity_create"),
    path("entities/<uuid:pk>/", views.entity_detail, name="entity_detail"),
    path("entities/<uuid:pk>/edit/", views.entity_edit, name="entity_edit"),

    # Backward-compat: redirect old client_list URL
    path("clients/", views.entity_list, name="client_list"),

    # Financial Years
    path("entities/<uuid:entity_pk>/years/create/", views.financial_year_create, name="financial_year_create"),
    path("years/<uuid:pk>/", views.financial_year_detail, name="financial_year_detail"),
    path("years/<uuid:pk>/status/", views.financial_year_status, name="financial_year_status"),
    path("years/<uuid:pk>/roll-forward/", views.roll_forward, name="roll_forward"),

    # Trial Balance
    path("years/<uuid:pk>/import/", views.trial_balance_import, name="trial_balance_import"),
    path("years/<uuid:pk>/trial-balance/", views.trial_balance_view, name="trial_balance_view"),
    path("years/<uuid:pk>/trial-balance/pdf/", views.trial_balance_pdf, name="trial_balance_pdf"),
    path("years/<uuid:pk>/trial-balance/download/", views.trial_balance_download, name="trial_balance_download"),

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
    path("documents/<uuid:pk>/delete/", views.delete_document, name="delete_document"),

    # Entity Officers / Signatories
    path("entities/<uuid:pk>/officers/", views.entity_officers, name="entity_officers"),
    path("entities/<uuid:entity_pk>/officers/create/", views.entity_officer_create, name="entity_officer_create"),
    path("officers/<uuid:pk>/edit/", views.entity_officer_edit, name="entity_officer_edit"),
    path("officers/<uuid:pk>/delete/", views.entity_officer_delete, name="entity_officer_delete"),

    # Access Ledger Import (admin)
    path("import/access-ledger/", views.access_ledger_import, name="access_ledger_import"),

    # Chart of Accounts
    path("chart-of-accounts/", views_audit.chart_of_accounts, name="chart_of_accounts"),
    path("api/chart-of-accounts/", views_audit.chart_of_accounts_api, name="chart_of_accounts_api"),

    # Audit Library
    path("audit-library/", views_audit.audit_library, name="audit_library"),

    # Risk Flags
    path("years/<uuid:pk>/risk-flags/", views_audit.risk_flags_view, name="risk_flags"),
    path("risk-flags/<uuid:pk>/resolve/", views_audit.resolve_risk_flag, name="resolve_risk_flag"),

    # Associates (now entity-level)
    path("entities/<uuid:entity_pk>/associates/create/", views.associate_create, name="associate_create"),
    path("associates/<uuid:pk>/edit/", views.associate_edit, name="associate_edit"),
    path("associates/<uuid:pk>/delete/", views.associate_delete, name="associate_delete"),

    # Accounting Software (now entity-level)
    path("entities/<uuid:entity_pk>/software/create/", views.software_create, name="software_create"),
    path("software/<uuid:pk>/edit/", views.software_edit, name="software_edit"),
    path("software/<uuid:pk>/delete/", views.software_delete, name="software_delete"),

    # Meeting Notes (now entity-level)
    path("entities/<uuid:entity_pk>/notes/create/", views.meeting_note_create, name="meeting_note_create"),
    path("notes/<uuid:pk>/", views.meeting_note_detail, name="meeting_note_detail"),
    path("notes/<uuid:pk>/edit/", views.meeting_note_edit, name="meeting_note_edit"),
    path("notes/<uuid:pk>/delete/", views.meeting_note_delete, name="meeting_note_delete"),
    path("notes/<uuid:pk>/toggle-followup/", views.meeting_note_toggle_followup, name="meeting_note_toggle_followup"),

    # GST Activity Statement
    path("years/<uuid:pk>/gst/", views.gst_activity_statement, name="gst_activity_statement"),
    path("years/<uuid:pk>/gst/download/", views.gst_activity_statement_download, name="gst_activity_statement_download"),

    # Depreciation
    path("years/<uuid:pk>/depreciation/add/", views.depreciation_add, name="depreciation_add"),
    path("depreciation/<uuid:pk>/edit/", views.depreciation_edit, name="depreciation_edit"),
    path("depreciation/<uuid:pk>/delete/", views.depreciation_delete, name="depreciation_delete"),
    path("years/<uuid:pk>/depreciation/roll-forward/", views.depreciation_roll_forward, name="depreciation_roll_forward"),

    # Stock
    path("years/<uuid:pk>/stock/add/", views.stock_add, name="stock_add"),
    path("stock/<uuid:pk>/edit/", views.stock_edit, name="stock_edit"),
    path("stock/<uuid:pk>/delete/", views.stock_delete, name="stock_delete"),
    path("years/<uuid:pk>/stock/push-to-tb/", views.stock_push_to_tb, name="stock_push_to_tb"),

    # Review → Trial Balance
    path("years/<uuid:pk>/review/push-to-tb/", views.review_push_to_tb, name="review_push_to_tb"),
    path("review-txn/<uuid:pk>/approve/", views.review_approve_transaction, name="review_approve_transaction"),
    path("years/<uuid:pk>/review/approve-all/", views.review_approve_all, name="review_approve_all"),

    # Notifications / Activity
    path("api/notifications/", views.notifications_api, name="notifications_api"),
    path("api/notifications/<uuid:pk>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("api/notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),

    # HTMX partials
    path("htmx/entity-search/", views.htmx_client_search, name="htmx_client_search"),
    path("htmx/tb-line/<uuid:pk>/map/", views.htmx_map_tb_line, name="htmx_map_tb_line"),

    # Bulk Actions (entity-level)
    path("entities/bulk-action/", views.entity_bulk_action, name="entity_bulk_action"),

    # Entity-level HandiLedger Import
    path("entities/<uuid:pk>/import-handiledger/", views.entity_import_handiledger, name="entity_import_handiledger"),

    # Delete Unfinalised FY Data
    path("entities/<uuid:pk>/delete-unfinalised/", views.delete_unfinalised_fy, name="delete_unfinalised_fy"),

    # HTMX: Update TB Line Mapping
    path("htmx/tb-line/<uuid:pk>/update-mapping/", views.htmx_update_tb_mapping, name="htmx_update_tb_mapping"),

    # COA Search API (for review tab dropdown)
    path("api/coa-search/", views.coa_search_api, name="coa_search_api"),

    # XRM Pull (Xero Practice Manager) — now entity-level
    path("entities/<uuid:pk>/xrm-search/", views.xrm_search, name="xrm_search"),
    path("entities/<uuid:pk>/xrm-pull/", views.xrm_pull, name="xrm_pull"),
]
