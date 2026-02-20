"""
Review app models.

These models serve as a local cache/mirror of Airtable data and provide
a local activity log. When the Airtable API key is configured, the views
will sync data from Airtable. Until then, mock data is used for display.

Enhanced with GST handling, entity linking, and a learning database for
per-client transaction pattern recognition.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings


class ReviewJob(models.Model):
    """
    Represents a bank statement processing job.
    Mirrors the Processing Jobs table in Airtable.
    """

    STATUS_CHOICES = [
        ("awaiting_review", "Awaiting Review"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
    ]

    SOURCE_CHOICES = [
        ("email", "Email Ingestion"),
        ("upload", "Manual Upload"),
        ("airtable", "Airtable Sync"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    airtable_record_id = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Airtable record ID for syncing (optional)",
    )
    entity = models.ForeignKey(
        "core.Entity", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="review_jobs",
        help_text="Linked entity for GST registration lookup",
    )
    client_name = models.CharField(max_length=255)
    file_name = models.CharField(max_length=500, blank=True, default="")
    submitted_by = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default="airtable",
    )
    total_transactions = models.IntegerField(default=0)
    auto_coded_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)
    confirmed_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="awaiting_review"
    )
    # Bank statement metadata
    bank_account_name = models.CharField(max_length=255, blank=True, default="")
    bsb = models.CharField(max_length=20, blank=True, default="")
    account_number = models.CharField(max_length=50, blank=True, default="")
    period_start = models.CharField(max_length=20, blank=True, default="")
    period_end = models.CharField(max_length=20, blank=True, default="")
    opening_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    closing_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
    )
    # GST flag (derived from entity but cached here for display)
    is_gst_registered = models.BooleanField(
        default=True,
        help_text="Whether GST applies to this job's transactions",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.client_name} — {self.file_name}"

    @property
    def progress_percent(self):
        if self.flagged_count == 0:
            return 0
        return int((self.confirmed_count / self.flagged_count) * 100)


class PendingTransaction(models.Model):
    """
    Represents a single flagged transaction awaiting review.
    Mirrors the Pending Review table in Airtable.
    Enhanced with GST breakdown fields.
    """

    TAX_TYPE_CHOICES = [
        ("", "— Select —"),
        ("GST on Income", "GST on Income"),
        ("GST on Expenses", "GST on Expenses"),
        ("GST Free Income", "GST Free Income"),
        ("GST Free Expenses", "GST Free Expenses"),
        ("Input Taxed", "Input Taxed"),
        ("BAS Excluded", "BAS Excluded"),
        ("N-T", "Not Reportable"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    airtable_record_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True,
    )
    job = models.ForeignKey(
        ReviewJob, on_delete=models.CASCADE, related_name="transactions"
    )
    date = models.CharField(max_length=20, blank=True, default="")
    description = models.CharField(max_length=500)
    # Amount fields — gross is the bank statement amount
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Gross amount from bank statement (inc GST if applicable)",
    )
    gst_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="GST component (amount/11 for GST items, 0 for GST-free)",
    )
    net_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Net amount excluding GST",
    )
    # AI suggestions
    ai_suggested_code = models.CharField(max_length=20, blank=True, default="")
    ai_suggested_name = models.CharField(max_length=255, blank=True, default="")
    ai_suggested_tax_type = models.CharField(max_length=30, blank=True, default="")
    ai_confidence = models.IntegerField(default=0, help_text="1-5 scale")
    ai_reasoning = models.TextField(blank=True, default="")
    # Confirmed by accountant
    confirmed_code = models.CharField(max_length=20, blank=True, default="")
    confirmed_name = models.CharField(max_length=255, blank=True, default="")
    confirmed_tax_type = models.CharField(
        max_length=30, blank=True, default="", choices=TAX_TYPE_CHOICES
    )
    confirmed_gst_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Accountant-confirmed GST amount (if different from AI calc)",
    )
    is_confirmed = models.BooleanField(default=False)
    from_learning = models.BooleanField(
        default=False,
        help_text="True if this classification came from the learning database",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "description"]

    def __str__(self):
        return f"{self.date} — {self.description} — ${self.amount}"

    def calculate_gst(self, tax_type=None, is_gst_registered=True):
        """
        Calculate GST based on tax type and registration status.
        Australian GST = 1/11 of the gross amount for GST-applicable items.
        """
        tt = tax_type or self.ai_suggested_tax_type or ""
        abs_amount = abs(self.amount)

        if not is_gst_registered or tt in ("GST Free Income", "GST Free Expenses",
                                            "BAS Excluded", "Input Taxed", "N-T", ""):
            self.gst_amount = Decimal("0.00")
            self.net_amount = abs_amount
        else:
            # GST on Income or GST on Expenses: GST = gross / 11
            self.gst_amount = (abs_amount / Decimal("11")).quantize(Decimal("0.01"))
            self.net_amount = (abs_amount - self.gst_amount).quantize(Decimal("0.01"))
        return self.gst_amount, self.net_amount


class TransactionPattern(models.Model):
    """
    Learning database for per-client transaction patterns.
    Stores confirmed mappings so future identical/similar transactions
    are auto-coded with high confidence.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(
        "core.Entity", on_delete=models.CASCADE, null=True, blank=True,
        related_name="transaction_patterns",
        help_text="Entity-specific pattern. Null = global pattern.",
    )
    description_pattern = models.CharField(
        max_length=500,
        help_text="Normalised transaction description for matching",
    )
    account_code = models.CharField(max_length=20)
    account_name = models.CharField(max_length=255)
    tax_type = models.CharField(max_length=30, blank=True, default="")
    usage_count = models.IntegerField(
        default=1,
        help_text="Number of times this pattern has been confirmed",
    )
    last_used = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-usage_count", "-last_used"]
        unique_together = ["entity", "description_pattern"]

    def __str__(self):
        return f"{self.description_pattern[:50]} -> {self.account_code} ({self.usage_count}x)"


class ReviewActivity(models.Model):
    """
    Activity log for the dashboard feed.
    """

    ACTIVITY_TYPES = [
        ("new_statement", "New statement received"),
        ("review_completed", "Review completed"),
        ("ai_improved", "AI accuracy improved"),
        ("review_started", "Review started"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPES)
    title = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Review activities"

    def __str__(self):
        return f"{self.get_activity_type_display()} — {self.title}"
