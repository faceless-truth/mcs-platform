"""
MCS Platform - Core Data Models
Implements the full data model from the specification:
Clients, Entities, Financial Years, Trial Balance Lines,
Account Mappings, Notes/Disclosures, Adjusting Journals, Audit Log.
"""
import uuid
from django.conf import settings
from django.db import models
from django.urls import reverse


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class Client(models.Model):
    """A client of MC & S. Each client can have multiple entities."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    assigned_accountant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_clients",
    )
    xpm_client_id = models.CharField(
        max_length=100, blank=True, verbose_name="XPM Client ID",
        help_text="Xero Practice Manager reference",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("core:client_detail", kwargs={"pk": self.pk})

    @property
    def entity_count(self):
        return self.entities.count()

    @property
    def latest_status(self):
        """Return the status of the most recent financial year across all entities."""
        fy = (
            FinancialYear.objects.filter(entity__client=self)
            .order_by("-end_date")
            .first()
        )
        return fy.get_status_display() if fy else "No data"


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------
class Entity(models.Model):
    """
    A legal entity belonging to a client.
    E.g., a company, trust, partnership, or sole trader.
    """

    class EntityType(models.TextChoices):
        COMPANY = "company", "Company"
        TRUST = "trust", "Trust"
        PARTNERSHIP = "partnership", "Partnership"
        SOLE_TRADER = "sole_trader", "Sole Trader"
        SMSF = "smsf", "SMSF"

    class ReportingFramework(models.TextChoices):
        GPFR_TIER1 = "GPFR_tier1", "General Purpose (Tier 1)"
        GPFR_TIER2 = "GPFR_tier2", "General Purpose (Tier 2)"
        SPFR = "SPFR", "Special Purpose"

    class CompanySize(models.TextChoices):
        SMALL = "small_proprietary", "Small Proprietary"
        LARGE = "large_proprietary", "Large Proprietary"
        PUBLIC = "public", "Public"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="entities"
    )
    entity_name = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=20, choices=EntityType.choices)
    abn = models.CharField(max_length=11, blank=True, verbose_name="ABN")
    acn = models.CharField(
        max_length=9, blank=True, verbose_name="ACN",
        help_text="Companies only",
    )
    registration_date = models.DateField(null=True, blank=True)
    financial_year_end = models.CharField(
        max_length=5, default="06-30",
        help_text="Month-day format, e.g. 06-30 for June",
    )
    reporting_framework = models.CharField(
        max_length=20,
        choices=ReportingFramework.choices,
        default=ReportingFramework.SPFR,
    )
    company_size = models.CharField(
        max_length=20,
        choices=CompanySize.choices,
        blank=True,
        help_text="Companies only",
    )
    template_id = models.ForeignKey(
        "FinancialStatementTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entities",
    )
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text="Flexible storage: directors, trustees, partners, registered address, etc.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_name"]
        verbose_name_plural = "entities"

    def __str__(self):
        return f"{self.entity_name} ({self.get_entity_type_display()})"

    def get_absolute_url(self):
        return reverse("core:entity_detail", kwargs={"pk": self.pk})


# ---------------------------------------------------------------------------
# Financial Year
# ---------------------------------------------------------------------------
class FinancialYear(models.Model):
    """A financial year for an entity. Links to prior year for comparatives."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In Review"
        REVIEWED = "reviewed", "Reviewed"
        FINALISED = "finalised", "Finalised"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="financial_years"
    )
    year_label = models.CharField(max_length=20, help_text='e.g. "FY2025"')
    start_date = models.DateField()
    end_date = models.DateField()
    prior_year = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_year",
        help_text="Link to prior year for comparatives",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_years",
    )
    finalised_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-end_date"]
        verbose_name_plural = "financial years"
        unique_together = ["entity", "year_label"]

    def __str__(self):
        return f"{self.entity.entity_name} - {self.year_label}"

    def get_absolute_url(self):
        return reverse("core:financial_year_detail", kwargs={"pk": self.pk})

    @property
    def is_locked(self):
        return self.status == self.Status.FINALISED


# ---------------------------------------------------------------------------
# Account Mapping (Standard Chart)
# ---------------------------------------------------------------------------
class AccountMapping(models.Model):
    """
    Defines how account codes map to standardised financial statement line items.
    This is the core logic layer of the system.
    """

    class FinancialStatement(models.TextChoices):
        INCOME_STATEMENT = "income_statement", "Income Statement"
        BALANCE_SHEET = "balance_sheet", "Balance Sheet"
        EQUITY = "equity", "Statement of Changes in Equity"
        CASH_FLOW = "cash_flow", "Cash Flow Statement"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    standard_code = models.CharField(
        max_length=20, unique=True,
        help_text='MC&S standard chart code, e.g. "REV001"',
    )
    line_item_label = models.CharField(
        max_length=255,
        help_text='Display label, e.g. "Revenue from contracts with customers"',
    )
    financial_statement = models.CharField(
        max_length=20, choices=FinancialStatement.choices
    )
    statement_section = models.CharField(
        max_length=100,
        help_text='e.g. "Current Assets", "Operating Revenue"',
    )
    display_order = models.IntegerField(default=0)
    note_trigger = models.ForeignKey(
        "NoteTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_by_mappings",
        help_text="Which disclosure note this line activates when non-zero",
    )
    applicable_entities = models.JSONField(
        default=list, blank=True,
        help_text='Entity types this applies to, e.g. ["company", "trust"]',
    )

    class Meta:
        ordering = ["financial_statement", "display_order"]

    def __str__(self):
        return f"{self.standard_code} - {self.line_item_label}"


# ---------------------------------------------------------------------------
# Client Account Mapping (per-entity mapping of client codes to standard codes)
# ---------------------------------------------------------------------------
class ClientAccountMapping(models.Model):
    """Maps a specific client account code to a standard AccountMapping line item."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="account_mappings"
    )
    client_account_code = models.CharField(max_length=20)
    client_account_name = models.CharField(max_length=255)
    mapped_line_item = models.ForeignKey(
        AccountMapping,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["entity", "client_account_code"]
        ordering = ["client_account_code"]

    def __str__(self):
        target = self.mapped_line_item.line_item_label if self.mapped_line_item else "UNMAPPED"
        return f"{self.client_account_code} -> {target}"


# ---------------------------------------------------------------------------
# Trial Balance Line
# ---------------------------------------------------------------------------
class TrialBalanceLine(models.Model):
    """
    A single account line in a trial balance.
    Highest-volume table (~200 lines per entity per year).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="trial_balance_lines"
    )
    account_code = models.CharField(max_length=20)
    account_name = models.CharField(max_length=255)
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    closing_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0
    )
    mapped_line_item = models.ForeignKey(
        AccountMapping,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trial_balance_lines",
    )
    is_adjustment = models.BooleanField(
        default=False,
        help_text="True if this line was created by an adjusting journal entry",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["account_code"]

    def __str__(self):
        return f"{self.account_code} - {self.account_name}: {self.closing_balance}"


# ---------------------------------------------------------------------------
# Note / Disclosure Template
# ---------------------------------------------------------------------------
class NoteTemplate(models.Model):
    """
    A disclosure note template for financial statements.
    Contains the note text with merge fields and trigger conditions.
    """

    class TriggerType(models.TextChoices):
        ALWAYS = "always", "Always (mandatory)"
        CONDITIONAL = "conditional", "Conditional (account-based)"
        ENTITY_BASED = "entity_based", "Entity-based"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note_number = models.IntegerField(help_text="Display order in financial statements")
    title = models.CharField(
        max_length=255,
        help_text='e.g. "Revenue", "Related Party Transactions"',
    )
    template_text = models.TextField(
        help_text="Note body with merge fields for dynamic data"
    )
    trigger_type = models.CharField(
        max_length=20, choices=TriggerType.choices
    )
    trigger_condition = models.JSONField(
        default=dict, blank=True,
        help_text="Conditions: account code ranges, entity types, thresholds, etc.",
    )
    applicable_entities = models.JSONField(
        default=list, blank=True,
        help_text='Entity types this note can appear for, e.g. ["company", "trust"]',
    )
    aasb_reference = models.CharField(
        max_length=50, blank=True,
        help_text='e.g. "AASB 15"',
    )
    last_reviewed = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["note_number"]

    def __str__(self):
        return f"Note {self.note_number}: {self.title}"


# ---------------------------------------------------------------------------
# Adjusting Journal
# ---------------------------------------------------------------------------
class AdjustingJournal(models.Model):
    """An adjusting journal entry for a financial year."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="adjusting_journals"
    )
    journal_date = models.DateField()
    description = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_journals",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-journal_date", "-created_at"]

    def __str__(self):
        return f"Journal {self.journal_date}: {self.description[:50]}"


class JournalLine(models.Model):
    """A single debit/credit line within an adjusting journal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal = models.ForeignKey(
        AdjustingJournal, on_delete=models.CASCADE, related_name="lines"
    )
    account_code = models.CharField(max_length=20)
    account_name = models.CharField(max_length=255)
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.account_code}: Dr {self.debit} / Cr {self.credit}"


# ---------------------------------------------------------------------------
# Financial Statement Template (Word document template)
# ---------------------------------------------------------------------------
class FinancialStatementTemplate(models.Model):
    """
    A Word document template for a specific entity type.
    Contains the base template file that gets populated with data.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    entity_type = models.CharField(
        max_length=20, choices=Entity.EntityType.choices
    )
    template_file = models.FileField(upload_to="templates/")
    description = models.TextField(blank=True)
    version = models.CharField(max_length=20, default="1.0")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_type", "name"]

    def __str__(self):
        return f"{self.name} (v{self.version})"


# ---------------------------------------------------------------------------
# Generated Document
# ---------------------------------------------------------------------------
class GeneratedDocument(models.Model):
    """A generated financial statement document (Word/PDF)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="generated_documents"
    )
    file = models.FileField(upload_to="generated/")
    file_format = models.CharField(max_length=10, default="docx")
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="generated_documents",
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.financial_year} - {self.file_format.upper()} ({self.generated_at:%Y-%m-%d})"


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """
    Tracks every significant action in the system for compliance and audit trail.
    """

    class Action(models.TextChoices):
        LOGIN = "login", "User Login"
        LOGOUT = "logout", "User Logout"
        IMPORT = "import", "Data Import"
        ADJUSTMENT = "adjustment", "Adjustment Created"
        GENERATE = "generate", "Document Generated"
        STATUS_CHANGE = "status_change", "Status Changed"
        MAPPING_CHANGE = "mapping_change", "Mapping Changed"
        USER_CHANGE = "user_change", "User Modified"
        TEMPLATE_CHANGE = "template_change", "Template Modified"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    description = models.TextField()
    affected_object_type = models.CharField(max_length=100, blank=True)
    affected_object_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} - {self.user} - {self.get_action_display()}"
