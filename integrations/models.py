"""
Integrations app models.

Stores OAuth2 connections to external accounting platforms (Xero, MYOB, QuickBooks).
Each Entity can have one active connection to one provider at a time.
"""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountingConnection(models.Model):
    """
    An OAuth2 connection between a StatementHub entity and an external
    accounting platform. Stores tokens, tenant/realm IDs, and connection
    metadata needed to pull trial balance data.
    """

    class Provider(models.TextChoices):
        XERO = "xero", "Xero"
        MYOB = "myob", "MYOB"
        QUICKBOOKS = "quickbooks", "QuickBooks Online"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Token Expired"
        DISCONNECTED = "disconnected", "Disconnected"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        "core.Entity",
        on_delete=models.CASCADE,
        related_name="accounting_connections",
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )

    # OAuth2 tokens
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)

    # Provider-specific identifiers
    # Xero: tenant_id (organisation UUID)
    # MYOB: company_file_uri
    # QuickBooks: realm_id (company ID)
    tenant_id = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Xero tenant ID, MYOB company file URI, or QBO realm ID",
    )
    tenant_name = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Display name of the connected organisation",
    )

    # Audit
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="accounting_connections",
    )
    connected_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-connected_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "provider"],
                condition=models.Q(status="active"),
                name="unique_active_connection_per_entity_provider",
            )
        ]

    def __str__(self):
        return f"{self.entity.entity_name} \u2192 {self.get_provider_display()} ({self.get_status_display()})"

    @property
    def is_token_expired(self):
        if not self.token_expires_at:
            return True
        return timezone.now() >= self.token_expires_at

    @property
    def needs_refresh(self):
        """Token needs refresh if it expires within 5 minutes."""
        if not self.token_expires_at:
            return True
        return timezone.now() >= (self.token_expires_at - timezone.timedelta(minutes=5))


class ImportLog(models.Model):
    """
    Log of each trial balance import from an external provider.
    Tracks what was pulled and any issues encountered.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(
        AccountingConnection,
        on_delete=models.CASCADE,
        related_name="import_logs",
    )
    financial_year = models.ForeignKey(
        "core.FinancialYear",
        on_delete=models.CASCADE,
        related_name="cloud_imports",
    )
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    lines_imported = models.IntegerField(default=0)
    lines_unmapped = models.IntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    as_at_date = models.DateField(
        null=True, blank=True,
        help_text="The date the trial balance was pulled as at",
    )
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-imported_at"]

    def __str__(self):
        return (
            f"{self.connection.get_provider_display()} import \u2192 "
            f"{self.financial_year} ({self.lines_imported} lines)"
        )
