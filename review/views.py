"""
Bank Statement Review views.

Provides the dashboard (pending reviews + activity feed), the transaction
review page, and API endpoints for the n8n webhook and transaction submission.
"""
import json
import logging
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PendingTransaction, ReviewActivity, ReviewJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Airtable configuration
# ---------------------------------------------------------------------------

AIRTABLE_BASE_ID = "appCIoC2AVqJ3axMG"
AIRTABLE_PENDING_TABLE = "tbl9XbFuVooVtBu2G"
AIRTABLE_JOBS_TABLE = "tblVXkcc3wFQCvQyv"
AIRTABLE_LEARNING_TABLE = "tblDO2k2wB3OSFBxa"


def _get_airtable_headers():
    """Return headers for Airtable API calls, or None if not configured."""
    api_key = getattr(settings, "AIRTABLE_API_KEY", None)
    if not api_key:
        return None
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _airtable_configured():
    return bool(getattr(settings, "AIRTABLE_API_KEY", None))


# ---------------------------------------------------------------------------
# Airtable sync — pull Pending Review records, group into jobs
# ---------------------------------------------------------------------------

def _sync_from_airtable():
    """
    Pull all records from the Pending Review table in Airtable.
    Group by (Batch ID prefix, Client Name) to create/update ReviewJobs.
    Each transaction becomes a PendingTransaction linked to its job.
    """
    import requests

    headers = _get_airtable_headers()
    if not headers:
        return False

    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

    try:
        # Fetch ALL records from Pending Review (paginated)
        all_records = []
        offset = None
        while True:
            params = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            resp = requests.get(
                f"{base_url}/{AIRTABLE_PENDING_TABLE}",
                headers=headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            all_records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break

        if not all_records:
            return True

        # Group records by Client Name (each client = one review job)
        # We use Client Name as the grouping key since all records for a client
        # belong to the same bank statement submission
        grouped = defaultdict(list)
        for rec in all_records:
            fields = rec.get("fields", {})
            client = fields.get("Client Name", "Unknown")
            grouped[client].append(rec)

        for client_name, records in grouped.items():
            # Determine job status based on transaction statuses
            statuses = [r["fields"].get("Status", "Pending") for r in records]
            all_confirmed = all(s == "Confirmed" for s in statuses)
            any_confirmed = any(s == "Confirmed" for s in statuses)

            if all_confirmed:
                job_status = "completed"
            elif any_confirmed:
                job_status = "in_progress"
            else:
                job_status = "awaiting_review"

            # Get the accountant email and batch info
            first_fields = records[0].get("fields", {})
            accountant_email = first_fields.get("Accountant Email", "")
            batch_id = first_fields.get("Batch ID", "")

            # Extract a common batch prefix (e.g. "batch-1771291" from "batch-1771291569184")
            # Use the first batch ID as the job identifier
            batch_prefix = batch_id.rsplit("-", 0)[0] if batch_id else client_name

            confirmed_count = sum(1 for s in statuses if s == "Confirmed")

            # Create or update the ReviewJob
            job, created = ReviewJob.objects.update_or_create(
                client_name=client_name,
                status__in=["awaiting_review", "in_progress"],
                defaults={
                    "file_name": f"Bank Statement — {len(records)} transactions",
                    "submitted_by": accountant_email or "Via bankstatements@mcands.com.au",
                    "total_transactions": len(records),
                    "auto_coded_count": len(records),  # All have AI suggestions
                    "flagged_count": len(records),
                    "confirmed_count": confirmed_count,
                    "status": job_status,
                },
            )

            if created:
                ReviewActivity.objects.create(
                    activity_type="new_statement",
                    title="New statement received",
                    description=f"{client_name} — {len(records)} transactions to review",
                )

            # Sync individual transactions
            for rec in records:
                fields = rec.get("fields", {})
                is_confirmed = fields.get("Status") == "Confirmed"

                PendingTransaction.objects.update_or_create(
                    airtable_record_id=rec["id"],
                    defaults={
                        "job": job,
                        "date": fields.get("Transaction Date", ""),
                        "description": fields.get("Description", ""),
                        "amount": fields.get("Amount", 0),
                        "ai_suggested_code": fields.get("AI Suggested Code", ""),
                        "ai_suggested_name": fields.get("AI Suggested Account", ""),
                        "ai_confidence": fields.get("AI Confidence", 0),
                        "ai_suggested_tax_type": fields.get("AI Suggested Tax Type", ""),
                        "confirmed_code": fields.get("Confirmed Code", ""),
                        "confirmed_name": fields.get("Confirmed Account", ""),
                        "confirmed_tax_type": fields.get("Confirmed Tax Type", ""),
                        "is_confirmed": is_confirmed,
                    },
                )

        return True

    except Exception as e:
        logger.error(f"Airtable sync failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def review_dashboard(request):
    """
    Dashboard view showing pending reviews and recent activity.
    This replaces the old dashboard as the homepage.
    """
    # Sync from Airtable if configured
    if _airtable_configured():
        _sync_from_airtable()

    pending_jobs = ReviewJob.objects.filter(
        status__in=["awaiting_review", "in_progress"]
    ).order_by("-received_at")

    completed_jobs = ReviewJob.objects.filter(
        status="completed"
    ).order_by("-completed_at")[:5]

    activities = ReviewActivity.objects.all().order_by("-created_at")[:10]

    context = {
        "pending_jobs": pending_jobs,
        "completed_jobs": completed_jobs,
        "activities": activities,
    }
    return render(request, "review/dashboard.html", context)


@login_required
def review_detail(request, pk):
    """
    Transaction review page for a specific job.
    Shows all flagged transactions with account picker and tax type dropdowns.
    """
    job = get_object_or_404(ReviewJob, pk=pk)
    transactions = job.transactions.all().order_by("date", "description")

    # Get chart of accounts for the picker
    # Use local account mappings from the core app
    from core.models import AccountMapping
    accounts = list(
        AccountMapping.objects.values_list("standard_code", "line_item_label")
        .order_by("standard_code")
    )
    accounts = [{"code": a[0], "name": a[1]} for a in accounts]

    context = {
        "job": job,
        "transactions": transactions,
        "accounts_json": json.dumps(accounts),
    }
    return render(request, "review/review_detail.html", context)


@login_required
@require_POST
def confirm_transaction(request, pk):
    """
    AJAX endpoint to confirm a single transaction.
    Updates the local record and pushes to Airtable.
    """
    txn = get_object_or_404(PendingTransaction, pk=pk)
    data = json.loads(request.body)

    txn.confirmed_code = data.get("confirmed_code", "")
    txn.confirmed_name = data.get("confirmed_name", "")
    txn.confirmed_tax_type = data.get("confirmed_tax_type", "")
    txn.is_confirmed = True
    txn.save()

    # Update job confirmed count
    job = txn.job
    job.confirmed_count = job.transactions.filter(is_confirmed=True).count()
    if job.confirmed_count > 0 and job.status == "awaiting_review":
        job.status = "in_progress"
    job.save()

    # Push to Airtable
    headers = _get_airtable_headers()
    if headers and txn.airtable_record_id:
        import requests as http_requests
        try:
            base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
            http_requests.patch(
                f"{base_url}/{AIRTABLE_PENDING_TABLE}/{txn.airtable_record_id}",
                headers=headers,
                json={
                    "fields": {
                        "Confirmed Code": txn.confirmed_code,
                        "Confirmed Account": txn.confirmed_name,
                        "Confirmed Tax Type": txn.confirmed_tax_type,
                        "Status": "Confirmed",
                    }
                },
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Failed to update Airtable: {e}")

    return JsonResponse({
        "status": "ok",
        "confirmed_count": job.confirmed_count,
        "flagged_count": job.flagged_count,
        "progress_percent": job.progress_percent,
    })


@login_required
@require_POST
def submit_review(request, pk):
    """
    Submit all confirmed transactions for a job.
    Marks the job as completed and batch-updates Airtable.
    """
    job = get_object_or_404(ReviewJob, pk=pk)

    # Check all transactions are confirmed
    unconfirmed = job.transactions.filter(is_confirmed=False).count()
    if unconfirmed > 0:
        return JsonResponse(
            {"status": "error", "message": f"{unconfirmed} transactions still need confirmation."},
            status=400,
        )

    # Batch update Airtable
    headers = _get_airtable_headers()
    if headers:
        import requests as http_requests
        base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

        # Batch update transactions (max 10 per request per Airtable limit)
        confirmed_txns = list(job.transactions.filter(
            is_confirmed=True
        ).exclude(airtable_record_id="").exclude(airtable_record_id__isnull=True))

        for i in range(0, len(confirmed_txns), 10):
            batch = confirmed_txns[i:i + 10]
            records = []
            for txn in batch:
                records.append({
                    "id": txn.airtable_record_id,
                    "fields": {
                        "Confirmed Code": txn.confirmed_code,
                        "Confirmed Account": txn.confirmed_name,
                        "Confirmed Tax Type": txn.confirmed_tax_type,
                        "Status": "Confirmed",
                    },
                })
            try:
                http_requests.patch(
                    f"{base_url}/{AIRTABLE_PENDING_TABLE}",
                    headers=headers,
                    json={"records": records},
                    timeout=15,
                )
            except Exception as e:
                logger.error(f"Airtable batch update failed: {e}")

    # Update local job
    job.status = "completed"
    job.completed_at = timezone.now()
    job.save()

    # Log activity
    ReviewActivity.objects.create(
        activity_type="review_completed",
        title="Review completed",
        description=f"{job.client_name} — {job.confirmed_count} transactions confirmed",
    )

    return JsonResponse({"status": "ok", "redirect": "/"})


@login_required
@require_POST
def accept_all_suggestions(request, pk):
    """
    Accept all AI suggestions for unconfirmed transactions in a job.
    Uses the AI suggested tax type if available, otherwise infers from amount.
    """
    job = get_object_or_404(ReviewJob, pk=pk)
    unconfirmed = job.transactions.filter(is_confirmed=False)

    for txn in unconfirmed:
        txn.confirmed_code = txn.ai_suggested_code
        txn.confirmed_name = txn.ai_suggested_name
        # Use AI suggested tax type if available
        if txn.ai_suggested_tax_type:
            txn.confirmed_tax_type = txn.ai_suggested_tax_type
        elif txn.amount > 0:
            txn.confirmed_tax_type = "GST on Income"
        else:
            txn.confirmed_tax_type = "GST on Expenses"
        txn.is_confirmed = True
        txn.save()

    job.confirmed_count = job.transactions.filter(is_confirmed=True).count()
    if job.status == "awaiting_review":
        job.status = "in_progress"
    job.save()

    return JsonResponse({
        "status": "ok",
        "confirmed_count": job.confirmed_count,
        "flagged_count": job.flagged_count,
    })


# ---------------------------------------------------------------------------
# Webhook endpoint (called by n8n)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def notify_new_review_job(request):
    """
    Webhook endpoint for n8n to notify StatementHub of a new review job.
    POST /api/notify/new-review-job
    """
    try:
        data = json.loads(request.body)
        job = ReviewJob.objects.create(
            airtable_record_id=data.get("airtable_record_id"),
            client_name=data.get("client_name", "Unknown"),
            file_name=data.get("file_name", ""),
            submitted_by=data.get("submitted_by", ""),
            total_transactions=data.get("total_transactions", 0),
            auto_coded_count=data.get("auto_coded_count", 0),
            flagged_count=data.get("flagged_count", 0),
            status="awaiting_review",
        )

        ReviewActivity.objects.create(
            activity_type="new_statement",
            title="New statement received",
            description=f"{job.client_name} — {job.flagged_count} transactions flagged",
        )

        return JsonResponse({"status": "ok", "job_id": str(job.id)})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
