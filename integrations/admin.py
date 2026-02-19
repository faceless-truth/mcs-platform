from django.contrib import admin
from .models import (
    AccountingConnection, ImportLog,
    XPMConnection, XPMSyncLog,
    XeroGlobalConnection, XeroTenant,
)


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


@admin.register(XeroGlobalConnection)
class XeroGlobalConnectionAdmin(admin.ModelAdmin):
    list_display = [
        "status", "connected_by", "connected_at",
        "last_tenant_refresh", "tenant_count",
    ]
    list_filter = ["status"]
    readonly_fields = ["id", "connected_at"]

    def tenant_count(self, obj):
        return obj.tenants.count()
    tenant_count.short_description = "Tenants"


@admin.register(XeroTenant)
class XeroTenantAdmin(admin.ModelAdmin):
    list_display = [
        "tenant_name", "tenant_id", "entity", "tenant_type", "updated_at",
    ]
    search_fields = ["tenant_name", "tenant_id"]
    list_filter = ["tenant_type"]
    raw_id_fields = ["entity"]
    readonly_fields = ["id", "created_at", "updated_at"]
