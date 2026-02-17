from django.contrib import admin
from .models import AccountingConnection, ImportLog


@admin.register(AccountingConnection)
class AccountingConnectionAdmin(admin.ModelAdmin):
    list_display = [
        "entity", "provider", "status", "tenant_name",
        "connected_by", "connected_at", "last_sync_at",
    ]
    list_filter = ["provider", "status"]
    search_fields = ["entity__entity_name", "tenant_name"]
    readonly_fields = ["id", "connected_at"]


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = [
        "connection", "financial_year", "lines_imported",
        "lines_unmapped", "imported_by", "imported_at",
    ]
    list_filter = ["connection__provider"]
    readonly_fields = ["id", "imported_at"]
