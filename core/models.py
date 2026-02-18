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
    trading_as = models.CharField(
        max_length=255, blank=True,
        help_text="Trading name, e.g. 'Southy's Structures'",
    )
    is_gst_registered = models.BooleanField(
        default=True,
        help_text="Whether this entity is registered for GST. Affects bank statement coding.",
    )
    show_cents = models.BooleanField(
        default=False,
        help_text="Show amounts with cents (2 decimal places). Default for trusts and sole traders.",
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
# Entity Officer / Signatory
# ---------------------------------------------------------------------------
class EntityOfficer(models.Model):
    """
    Directors, partners, trustees, or beneficiaries of an entity.
    These are used on declaration pages and signature blocks of financial statements.
    Officers are set once per entity and rolled forward each year.
    """

    class OfficerRole(models.TextChoices):
        DIRECTOR = "director", "Director"
        PARTNER = "partner", "Partner"
        TRUSTEE = "trustee", "Trustee"
        BENEFICIARY = "beneficiary", "Beneficiary"
        SECRETARY = "secretary", "Secretary"
        PUBLIC_OFFICER = "public_officer", "Public Officer"
        SOLE_TRADER = "sole_trader", "Sole Trader / Proprietor"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="officers"
    )
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=OfficerRole.choices)
    title = models.CharField(
        max_length=50, blank=True,
        help_text='Optional title, e.g. "Managing Director", "Senior Partner"',
    )
    date_appointed = models.DateField(null=True, blank=True)
    date_ceased = models.DateField(null=True, blank=True)
    is_signatory = models.BooleanField(
        default=True,
        help_text="Whether this person signs the financial statements",
    )
    display_order = models.IntegerField(
        default=0,
        help_text="Order in which signatories appear on declaration page",
    )
    # For partnerships: profit share percentage
    profit_share_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Partnership profit share % (partnerships only)",
    )
    # For trusts: beneficiary distribution percentage
    distribution_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Distribution % (trust beneficiaries only)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity", "display_order", "full_name"]
        verbose_name = "Entity Officer / Signatory"
        verbose_name_plural = "Entity Officers / Signatories"

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()}) - {self.entity.entity_name}"

    @property
    def is_active(self):
        """Officer is active if they have not ceased."""
        return self.date_ceased is None


# ---------------------------------------------------------------------------
# Financial Year
# ---------------------------------------------------------------------------
class FinancialYear(models.Model):
    """A financial year for an entity. Links to prior year for comparatives."""

    class PeriodType(models.TextChoices):
        ANNUAL = "annual", "Annual (Full Year)"
        HALF_YEAR = "half_year", "Half-Year"
        QUARTERLY = "quarterly", "Quarterly"
        MONTHLY = "monthly", "Monthly"
        INTERIM = "interim", "Interim (Custom Period)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In Review"
        REVIEWED = "reviewed", "Reviewed"
        FINALISED = "finalised", "Finalised"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="financial_years"
    )
    year_label = models.CharField(max_length=20, help_text='e.g. "FY2025" or "Q1 2025"')
    period_type = models.CharField(
        max_length=20,
        choices=PeriodType.choices,
        default=PeriodType.ANNUAL,
        help_text="Type of reporting period",
    )
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
# Chart of Account (entity-type-specific detailed accounts)
# ---------------------------------------------------------------------------
class ChartOfAccount(models.Model):
    """
    Entity-type-specific chart of accounts.
    These are the detailed account codes (e.g. 0500 Sales, 1510 Accountancy)
    that transactions and trial balance lines are coded to.
    Each entity type (Company, Trust, Partnership, Sole Trader) has its own
    set of accounts. These accounts roll up to AccountMapping line items
    for financial statement generation.
    """

    class StatementSection(models.TextChoices):
        SUSPENSE = "suspense", "Suspense"
        REVENUE = "revenue", "Revenue"
        COST_OF_SALES = "cost_of_sales", "Cost of Sales"
        EXPENSES = "expenses", "Expenses"
        ASSETS = "assets", "Assets"
        LIABILITIES = "liabilities", "Liabilities"
        EQUITY = "equity", "Equity"
        CAPITAL_ACCOUNTS = "capital_accounts", "Capital Accounts"
        PL_APPROPRIATION = "pl_appropriation", "P&L Appropriation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(
        max_length=20, choices=Entity.EntityType.choices,
        help_text="Which entity type this account belongs to",
    )
    account_code = models.CharField(
        max_length=20,
        help_text='Account code, e.g. "0500", "1510", "2000.01"',
    )
    account_name = models.CharField(
        max_length=255,
        help_text='Account name, e.g. "Sales", "Accountancy"',
    )
    classification = models.CharField(
        max_length=255, blank=True, default="",
        help_text='Tax classification, e.g. "Other sales revenue", "Trading income"',
    )
    section = models.CharField(
        max_length=30, choices=StatementSection.choices,
        help_text="Which section of the financial statements this belongs to",
    )
    tax_code = models.CharField(
        max_length=20, blank=True, default="",
        help_text='Default tax code: GST, ADS, ITS, FRE, CAP, INP, etc.',
    )
    maps_to = models.ForeignKey(
        "AccountMapping",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="detailed_accounts",
        help_text="Which financial statement line item this rolls up to",
    )
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(
        default=0,
        help_text="Sort order within the section",
    )

    class Meta:
        ordering = ["entity_type", "section", "account_code"]
        unique_together = ["entity_type", "account_code"]
        indexes = [
            models.Index(fields=["entity_type", "section"]),
            models.Index(fields=["entity_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.account_code} — {self.account_name} ({self.get_entity_type_display()})"

    @property
    def is_revenue(self):
        return self.section in (self.StatementSection.REVENUE, self.StatementSection.COST_OF_SALES)

    @property
    def is_expense(self):
        return self.section == self.StatementSection.EXPENSES

    @property
    def is_balance_sheet(self):
        return self.section in (
            self.StatementSection.ASSETS,
            self.StatementSection.LIABILITIES,
            self.StatementSection.EQUITY,
            self.StatementSection.CAPITAL_ACCOUNTS,
        )


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
    prior_debit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Prior year debit amount for comparative column",
    )
    prior_credit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Prior year credit amount for comparative column",
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
# Depreciation Asset
# ---------------------------------------------------------------------------
class DepreciationAsset(models.Model):
    """
    An individual depreciable asset for the depreciation schedule.
    Grouped by category (Furniture & Fixtures, Plant & Equipment, etc.).
    """

    class DepreciationMethod(models.TextChoices):
        DIMINISHING = "D", "Diminishing Value"
        PRIME_COST = "P", "Prime Cost"
        WRITTEN_OFF = "W", "Written Off"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="depreciation_assets"
    )
    category = models.CharField(
        max_length=100,
        help_text='Asset category, e.g. "Furniture and Fixtures", "Motor Vehicles"',
    )
    asset_name = models.CharField(max_length=255)
    purchase_date = models.DateField(null=True, blank=True)
    total_cost = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Original purchase cost",
    )
    private_use_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Private use percentage (0-100)",
    )
    opening_wdv = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Opening WDV",
    )
    # Disposal fields
    disposal_date = models.DateField(null=True, blank=True)
    disposal_consideration = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    # Addition fields
    addition_date = models.DateField(null=True, blank=True)
    addition_cost = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    # Depreciation fields
    depreciable_value = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Value on which depreciation is calculated",
    )
    method = models.CharField(
        max_length=1,
        choices=DepreciationMethod.choices,
        default=DepreciationMethod.DIMINISHING,
    )
    rate = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
        help_text="Depreciation rate as percentage",
    )
    depreciation_amount = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Depreciation charged this year",
    )
    private_depreciation = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Private portion of depreciation",
    )
    closing_wdv = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        verbose_name="Closing WDV",
    )
    # Profit/Loss on disposal
    profit_on_disposal = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    loss_on_disposal = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "display_order", "asset_name"]
        verbose_name = "Depreciation Asset"
        verbose_name_plural = "Depreciation Assets"

    def __str__(self):
        return f"{self.asset_name} ({self.category}) - WDV: {self.closing_wdv}"


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

    class JournalType(models.TextChoices):
        GENERAL = "general", "General Journal"
        ADJUSTING = "adjusting", "Adjusting Entry"
        YEAR_END = "year_end", "Year-End Entry"
        DEPRECIATION = "depreciation", "Depreciation Entry"
        TAX = "tax", "Tax Adjustment"

    class JournalStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="adjusting_journals"
    )
    reference_number = models.CharField(
        max_length=20, blank=True,
        help_text="Auto-generated sequential reference, e.g. JE-001",
    )
    journal_type = models.CharField(
        max_length=20,
        choices=JournalType.choices,
        default=JournalType.GENERAL,
    )
    status = models.CharField(
        max_length=20,
        choices=JournalStatus.choices,
        default=JournalStatus.DRAFT,
    )
    journal_date = models.DateField()
    description = models.TextField()
    narration = models.TextField(
        blank=True,
        help_text="Additional notes or explanation for audit purposes",
    )
    total_debit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Cached total debit for quick display",
    )
    total_credit = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Cached total credit for quick display",
    )
    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_journals",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_journals",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-journal_date", "-created_at"]

    def __str__(self):
        ref = self.reference_number or "DRAFT"
        return f"{ref} - {self.journal_date}: {self.description[:50]}"

    def save(self, *args, **kwargs):
        """Auto-generate reference number on first save."""
        if not self.reference_number and self.financial_year_id:
            last = (
                AdjustingJournal.objects
                .filter(financial_year=self.financial_year)
                .exclude(reference_number="")
                .order_by("-reference_number")
                .first()
            )
            if last and last.reference_number:
                try:
                    num = int(last.reference_number.split("-")[1]) + 1
                except (IndexError, ValueError):
                    num = 1
            else:
                num = 1
            self.reference_number = f"JE-{num:03d}"
        super().save(*args, **kwargs)

    @property
    def is_balanced(self):
        return self.total_debit == self.total_credit

    @property
    def can_post(self):
        return self.status == self.JournalStatus.DRAFT and self.is_balanced

    @property
    def can_delete(self):
        """Any journal can be deleted if the year is not locked."""
        return not self.financial_year.is_locked

    def recalculate_totals(self):
        """Recalculate cached totals from lines."""
        from django.db.models import Sum as DSum
        agg = self.lines.aggregate(dr=DSum("debit"), cr=DSum("credit"))
        self.total_debit = agg["dr"] or 0
        self.total_credit = agg["cr"] or 0
        self.save(update_fields=["total_debit", "total_credit"])


class JournalLine(models.Model):
    """A single debit/credit line within an adjusting journal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal = models.ForeignKey(
        AdjustingJournal, on_delete=models.CASCADE, related_name="lines"
    )
    line_number = models.IntegerField(
        default=0,
        help_text="Display order within the journal",
    )
    account_code = models.CharField(max_length=20)
    account_name = models.CharField(max_length=255)
    description = models.CharField(
        max_length=255, blank=True,
        help_text="Optional per-line description",
    )
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        ordering = ["line_number", "id"]

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


# ---------------------------------------------------------------------------
# Risk Rule (Audit Risk Engine)
# ---------------------------------------------------------------------------
class RiskRule(models.Model):
    """
    Defines an audit risk rule that is evaluated against financial year data.
    Each rule has a trigger configuration and produces RiskFlags when triggered.
    """

    class Category(models.TextChoices):
        VARIANCE = "variance", "Variance Analysis"
        CGT = "cgt", "Capital Gains Tax"
        DIVISION_7A = "division_7a", "Division 7A"
        EXPENSES = "expenses", "Expense Analysis"
        FBT = "fbt", "Fringe Benefits Tax"
        GENERAL = "general", "General"
        GST = "gst", "GST"
        SOLVENCY = "solvency", "Solvency"
        SUPERANNUATION = "superannuation", "Superannuation"
        TRUST = "trust", "Trust"
        RELATED_PARTY = "related_party", "Related Party"

    class Severity(models.TextChoices):
        CRITICAL = "CRITICAL", "Critical"
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"

    rule_id = models.CharField(max_length=20, primary_key=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    title = models.CharField(max_length=255)
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=Severity.choices)
    tier = models.IntegerField(
        help_text="Processing tier: 1=variance analysis, 2=compliance checks"
    )
    applicable_entities = models.JSONField(
        default=list,
        help_text='Entity types this rule applies to, e.g. ["company", "trust"]',
    )
    trigger_config = models.JSONField(
        default=dict,
        help_text="Configuration for how this rule evaluates data",
    )
    recommended_action = models.TextField()
    legislation_ref = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tier", "rule_id"]

    def __str__(self):
        return f"[{self.rule_id}] {self.title} ({self.get_severity_display()})"


# ---------------------------------------------------------------------------
# Risk Reference Data
# ---------------------------------------------------------------------------
class RiskReferenceData(models.Model):
    """
    Reference thresholds and values used by risk rules.
    E.g., GST registration threshold, super guarantee rate, etc.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    description = models.TextField()
    applicable_fy = models.CharField(
        max_length=10, blank=True,
        help_text='Financial year this applies to, e.g. "FY2025" or blank for all',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_reference_data",
    )

    class Meta:
        ordering = ["key"]
        verbose_name = "Risk Reference Data"
        verbose_name_plural = "Risk Reference Data"

    def __str__(self):
        return f"{self.key} = {self.value}"


# ---------------------------------------------------------------------------
# Risk Flag (Audit Risk Alert)
# ---------------------------------------------------------------------------
class RiskFlag(models.Model):
    """
    A specific risk flag raised against a financial year after running the
    audit risk engine. Each flag references a RiskRule and contains the
    specific details of what was found.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed"
        RESOLVED = "resolved", "Resolved"
        AUTO_RESOLVED = "auto_resolved", "Auto-Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="risk_flags"
    )
    run_id = models.UUIDField(
        help_text="Groups flags from the same analysis run"
    )
    rule_id = models.CharField(max_length=20)
    tier = models.IntegerField()
    severity = models.CharField(max_length=10)
    title = models.CharField(max_length=255)
    description = models.TextField()
    affected_accounts = models.JSONField(default=list)
    calculated_values = models.JSONField(default=dict)
    recommended_action = models.TextField()
    legislation_ref = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_risk_flags",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["financial_year", "status"]),
            models.Index(fields=["financial_year", "severity"]),
            models.Index(fields=["run_id"]),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title} - {self.financial_year}"


# ---------------------------------------------------------------------------
# Client Associate (Related Parties)
# ---------------------------------------------------------------------------
class ClientAssociate(models.Model):
    """
    Tracks related parties and associates of a client.
    Used for related party transaction detection in the audit risk engine.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="associates"
    )
    name = models.CharField(max_length=255)
    relationship_type = models.CharField(
        max_length=50,
        help_text='e.g. "Director", "Related Entity", "Shareholder"',
    )
    abn = models.CharField(max_length=11, blank=True, verbose_name="ABN")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    related_entity = models.ForeignKey(
        Entity, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="associated_as",
        help_text="Link to an entity in the system if applicable",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["client", "name"]

    def __str__(self):
        return f"{self.name} ({self.relationship_type}) - {self.client.name}"
