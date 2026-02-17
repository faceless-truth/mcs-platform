"""
Review app models.

These models serve as a local cache/mirror of Airtable data and provide
a local activity log. When the Airtable API key is configured, the views
will sync data from Airtable. Until then, mock data is used for display.
"""
import uuid
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    airtable_record_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True,
        help_text="Airtable record ID for syncing",
    )
    client_name = models.CharField(max_length=255)
    file_name = models.CharField(max_length=500, blank=True, default="")
    submitted_by = models.CharField(max_length=255, blank=True, default="")
    total_transactions = models.IntegerField(default=0)
    auto_coded_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)
    confirmed_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="awaiting_review"
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
    """

    TAX_TYPE_CHOICES = [
        ("", "— Select —"),
        ("GST on Income", "GST on Income"),
        ("GST on Expenses", "GST on Expenses"),
        ("GST Free Income", "GST Free Income"),
        ("GST Free Expenses", "GST Free Expenses"),
        ("BAS Excluded", "BAS Excluded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    airtable_record_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True,
    )
    job = models.ForeignKey(
        ReviewJob, on_delete=models.CASCADE, related_name="transactions"
    )
    date = models.DateField()
    description = models.CharField(max_length=500)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    ai_suggested_code = models.CharField(max_length=20, blank=True, default="")
    ai_suggested_name = models.CharField(max_length=255, blank=True, default="")
    ai_confidence = models.IntegerField(default=0, help_text="1-5 scale")
    confirmed_code = models.CharField(max_length=20, blank=True, default="")
    confirmed_name = models.CharField(max_length=255, blank=True, default="")
    confirmed_tax_type = models.CharField(
        max_length=30, blank=True, default="", choices=TAX_TYPE_CHOICES
    )
    is_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "description"]

    def __str__(self):
        return f"{self.date} — {self.description} — ${self.amount}"


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
