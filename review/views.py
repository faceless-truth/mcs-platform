"""
Bank Statement Review views.

Provides the dashboard (pending reviews + activity feed), the transaction
review page, and API endpoints for the n8n webhook and transaction submission.
"""
import json
import logging
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
# Airtable integration helpers (used when AIRTABLE_API_KEY is configured)
# ---------------------------------------------------------------------------

def _get_airtable_headers():
    """Return headers for Airtable API calls, or None if not configured."""
    api_key = getattr(settings, "AIRTABLE_API_KEY", None)
    if not api_key:
        return None
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


AIRTABLE_BASE_ID = "appCIoC2AVqJ3axMG"
AIRTABLE_JOBS_TABLE = "tblVXkcc3wFQCvQyv"
AIRTABLE_PENDING_TABLE = "tbl9XbFuVooVtBu2G"
AIRTABLE_COA_TABLE = "tblLqV2ASu4r3jF1s"


def _sync_from_airtable():
    """
    Sync review jobs and pending transactions from Airtable.
    Called on dashboard load when Airtable is configured.
    """
    import requests

    headers = _get_airtable_headers()
    if not headers:
        return False

    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

    try:
        # Fetch jobs with Status = 'Awaiting Review' or recently completed
        resp = requests.get(
            f"{base_url}/{AIRTABLE_JOBS_TABLE}",
            headers=headers,
            params={"filterByFormula": "OR(Status='Awaiting Review', Status='Completed')"},
            timeout=10,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])

        for rec in records:
            fields = rec.get("fields", {})
            status_map = {
                "Awaiting Review": "awaiting_review",
                "In Progress": "in_progress",
                "Completed": "completed",
            }
            status = status_map.get(fields.get("Status", ""), "awaiting_review")

            job, created = ReviewJob.objects.update_or_create(
                airtable_record_id=rec["id"],
                defaults={
                    "client_name": fields.get("Client Name", "Unknown"),
                    "file_name": fields.get("File Name", ""),
                    "submitted_by": fields.get("Submitted By", ""),
                    "total_transactions": fields.get("Total Transactions", 0),
                    "auto_coded_count": fields.get("Auto Coded Count", 0),
                    "flagged_count": fields.get("Flagged Count", 0),
                    "confirmed_count": fields.get("Confirmed Count", 0),
                    "status": status,
                },
            )

            if created:
                ReviewActivity.objects.create(
                    activity_type="new_statement",
                    title="New statement received",
                    description=f"{job.client_name} — {job.flagged_count} transactions flagged",
                )

        # Fetch pending transactions for awaiting jobs
        awaiting_jobs = ReviewJob.objects.filter(status="awaiting_review")
        for job in awaiting_jobs:
            if not job.airtable_record_id:
                continue
            resp = requests.get(
                f"{base_url}/{AIRTABLE_PENDING_TABLE}",
                headers=headers,
                params={
                    "filterByFormula": f"{{Job ID}}='{job.airtable_record_id}'"
                },
                timeout=10,
            )
            resp.raise_for_status()
            txn_records = resp.json().get("records", [])

            for txn_rec in txn_records:
                tf = txn_rec.get("fields", {})
                PendingTransaction.objects.update_or_create(
                    airtable_record_id=txn_rec["id"],
                    defaults={
                        "job": job,
                        "date": tf.get("Date", timezone.now().date().isoformat()),
                        "description": tf.get("Description", ""),
                        "amount": tf.get("Amount", 0),
                        "ai_suggested_code": tf.get("AI Suggested Code", ""),
                        "ai_suggested_name": tf.get("AI Suggested Name", ""),
                        "ai_confidence": tf.get("AI Confidence", 0),
                        "confirmed_code": tf.get("Confirmed Code", ""),
                        "confirmed_name": tf.get("Confirmed Name", ""),
                        "confirmed_tax_type": tf.get("Confirmed Tax Type", ""),
                        "is_confirmed": bool(tf.get("Confirmed Code")),
                    },
                )

        return True
    except Exception as e:
        logger.error(f"Airtable sync failed: {e}")
        return False


def _fetch_chart_of_accounts():
    """Fetch chart of accounts from Airtable for the account picker."""
    import requests

    headers = _get_airtable_headers()
    if not headers:
        return []

    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
    accounts = []

    try:
        offset = None
        while True:
            params = {}
            if offset:
                params["offset"] = offset
            resp = requests.get(
                f"{base_url}/{AIRTABLE_COA_TABLE}",
                headers=headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            for rec in data.get("records", []):
                fields = rec.get("fields", {})
                accounts.append({
                    "code": fields.get("Code", ""),
                    "name": fields.get("Name", ""),
                })
            offset = data.get("offset")
            if not offset:
                break
        return sorted(accounts, key=lambda a: a["code"])
    except Exception as e:
        logger.error(f"Failed to fetch chart of accounts: {e}")
        return []


# ---------------------------------------------------------------------------
# Mock data (used when Airtable is not yet configured)
# ---------------------------------------------------------------------------

def _ensure_mock_data():
    """Create mock data if no review jobs exist and Airtable is not configured."""
    if ReviewJob.objects.exists():
        return

    now = timezone.now()

    # Job 1 - Awaiting Review, 0 confirmed
    job1 = ReviewJob.objects.create(
        client_name="Veronica Cerratti Pty Ltd",
        file_name="BankStatement_Jan2026.pdf",
        submitted_by="Harry Gan",
        total_transactions=78,
        auto_coded_count=54,
        flagged_count=24,
        confirmed_count=0,
        status="awaiting_review",
        received_at=now - timedelta(hours=2),
    )

    # Job 2 - Awaiting Review, partially confirmed
    job2 = ReviewJob.objects.create(
        client_name="Neri Family Trust",
        file_name="NAB_Statement_Dec2025.pdf",
        submitted_by="Brooke Austin",
        total_transactions=42,
        auto_coded_count=34,
        flagged_count=8,
        confirmed_count=5,
        status="awaiting_review",
        received_at=now - timedelta(days=1),
    )

    # Job 3 - Awaiting Review
    job3 = ReviewJob.objects.create(
        client_name="Foothills Conference Centre Pty Ltd",
        file_name="CBA_Statement_Feb2026.pdf",
        submitted_by="Elio Scarton",
        total_transactions=65,
        auto_coded_count=53,
        flagged_count=12,
        confirmed_count=0,
        status="awaiting_review",
        received_at=now - timedelta(days=2),
    )

    # Job 4 - Completed
    ReviewJob.objects.create(
        client_name="Mr Phillip North",
        file_name="Westpac_Jan2026.pdf",
        submitted_by="Elio Scarton",
        total_transactions=28,
        auto_coded_count=22,
        flagged_count=6,
        confirmed_count=6,
        status="completed",
        received_at=now - timedelta(days=3),
        completed_at=now - timedelta(days=3, hours=-2),
    )

    # Mock transactions for Job 1
    mock_txns = [
        {"date": "2026-01-03", "desc": "CALTEX KEYSBOROUGH AU", "amount": -72.50, "code": "1710", "name": "Fuel & oil", "conf": 3},
        {"date": "2026-01-05", "desc": "BUNNINGS 4251 KEYSBOROUGH", "amount": -234.80, "code": "1715", "name": "General expenses", "conf": 2},
        {"date": "2026-01-06", "desc": "OFFICEWORKS 1042 DANDENONG", "amount": -189.95, "code": "1715", "name": "General expenses", "conf": 3},
        {"date": "2026-01-07", "desc": "TRANSFER TO SAVINGS ACC 4821", "amount": -5000.00, "code": "3565", "name": "Loan - Director", "conf": 1},
        {"date": "2026-01-08", "desc": "RACV INSURANCE RENEWAL", "amount": -1245.60, "code": "1755", "name": "Insurance", "conf": 3},
        {"date": "2026-01-09", "desc": "CITY OF CASEY RATES", "amount": -892.30, "code": "1715", "name": "General expenses", "conf": 2},
        {"date": "2026-01-10", "desc": "TELSTRA BILL PAYMENT", "amount": -165.00, "code": "1940", "name": "Telephone", "conf": 3},
        {"date": "2026-01-12", "desc": "PAYMENT TO J SMITH CONSULTING", "amount": -3300.00, "code": "1798", "name": "Management fees", "conf": 2},
        {"date": "2026-01-14", "desc": "DIRECT DEBIT - ATO IAS DEC", "amount": -4800.00, "code": "1715", "name": "General expenses", "conf": 1},
        {"date": "2026-01-15", "desc": "DEPOSIT - CASH", "amount": 2450.00, "code": "1000", "name": "Sales/Fees/Commissions", "conf": 3},
        {"date": "2026-01-16", "desc": "SUPERCHEAP AUTO DANDENONG", "amount": -87.40, "code": "1808", "name": "M/V car - Repairs", "conf": 3},
        {"date": "2026-01-18", "desc": "ANZ BANK FEES MONTHLY", "amount": -30.00, "code": "1545", "name": "Bank fees & charges", "conf": 3},
        {"date": "2026-01-19", "desc": "WOOLWORTHS 3175 DANDENONG", "amount": -156.20, "code": "1715", "name": "General expenses", "conf": 2},
        {"date": "2026-01-20", "desc": "PAYPAL *CANVA", "amount": -17.99, "code": "1515", "name": "Advertising & promotion", "conf": 2},
        {"date": "2026-01-21", "desc": "DIRECT CREDIT - SMITH J", "amount": 1500.00, "code": "1000", "name": "Sales/Fees/Commissions", "conf": 2},
        {"date": "2026-01-22", "desc": "CLEANAWAY WASTE SERVICES", "amount": -385.00, "code": "1565", "name": "Cleaning & rubbish removal", "conf": 3},
        {"date": "2026-01-23", "desc": "ORIGIN ENERGY BILL", "amount": -412.55, "code": "1680", "name": "Gas & electricity", "conf": 4},
        {"date": "2026-01-24", "desc": "KMART 3175 DANDENONG", "amount": -89.00, "code": "1715", "name": "General expenses", "conf": 2},
        {"date": "2026-01-25", "desc": "TRANSFER FROM SAVINGS", "amount": 10000.00, "code": "3565", "name": "Loan - Director", "conf": 1},
        {"date": "2026-01-26", "desc": "EFTPOS PURCHASE - TOTAL TOOLS", "amount": -267.50, "code": "1715", "name": "General expenses", "conf": 2},
        {"date": "2026-01-27", "desc": "ATO - PAYG WITHHOLDING", "amount": -3200.00, "code": "3050", "name": "PAYG withholding payable", "conf": 3},
        {"date": "2026-01-28", "desc": "SUPER GUARANTEE - AUST SUPER", "amount": -1850.00, "code": "1930", "name": "Superannuation", "conf": 4},
        {"date": "2026-01-29", "desc": "WAGES - NET PAY", "amount": -8500.00, "code": "1960", "name": "Wages & salaries", "conf": 4},
        {"date": "2026-01-31", "desc": "INTEREST CHARGED", "amount": -12.45, "code": "1545", "name": "Bank fees & charges", "conf": 3},
    ]

    for txn in mock_txns:
        PendingTransaction.objects.create(
            job=job1,
            date=txn["date"],
            description=txn["desc"],
            amount=txn["amount"],
            ai_suggested_code=txn["code"],
            ai_suggested_name=txn["name"],
            ai_confidence=txn["conf"],
        )

    # Mock activity
    ReviewActivity.objects.create(
        activity_type="new_statement",
        title="New statement received",
        description="Veronica Cerratti Pty Ltd — 24 transactions flagged",
    )
    ReviewActivity.objects.create(
        activity_type="review_completed",
        title="Review completed",
        description="Mr Phillip North — Excel emailed to Elio",
    )
    ReviewActivity.objects.create(
        activity_type="ai_improved",
        title="AI accuracy improved",
        description="Learning database updated with 6 new mappings",
    )
    ReviewActivity.objects.create(
        activity_type="new_statement",
        title="New statement received",
        description="Neri Family Trust — 8 transactions flagged",
    )
    ReviewActivity.objects.create(
        activity_type="review_completed",
        title="Review completed",
        description="ABC Holdings — Excel emailed to Harry",
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def review_dashboard(request):
    """
    Dashboard view showing pending reviews and recent activity.
    This replaces the old dashboard as the homepage.
    """
    # Try to sync from Airtable if configured
    headers = _get_airtable_headers()
    if headers:
        _sync_from_airtable()
    else:
        _ensure_mock_data()

    pending_jobs = ReviewJob.objects.filter(status="awaiting_review")
    completed_jobs = ReviewJob.objects.filter(status="completed")[:5]
    activities = ReviewActivity.objects.all()[:10]

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
    transactions = job.transactions.all()

    # Get chart of accounts for the picker
    # Try Airtable first, fall back to local trial balance accounts
    accounts = _fetch_chart_of_accounts()
    if not accounts:
        # Fall back to local account data from core app
        from core.models import AccountMapping
        accounts = list(
            AccountMapping.objects.values_list("code", "aasb_label")
            .order_by("code")
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
    Updates the local record and optionally pushes to Airtable.
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
    job.save()

    # Push to Airtable if configured
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
                        "Confirmed Tax Type": txn.confirmed_tax_type,
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
    Marks the job as completed and pushes to Airtable.
    """
    job = get_object_or_404(ReviewJob, pk=pk)

    # Check all transactions are confirmed
    unconfirmed = job.transactions.filter(is_confirmed=False).count()
    if unconfirmed > 0:
        return JsonResponse(
            {"status": "error", "message": f"{unconfirmed} transactions still need confirmation."},
            status=400,
        )

    # Batch update Airtable if configured
    headers = _get_airtable_headers()
    if headers:
        import requests as http_requests
        base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

        # Batch update transactions (max 10 per request)
        confirmed_txns = list(job.transactions.filter(
            is_confirmed=True, airtable_record_id__isnull=False
        ))
        for i in range(0, len(confirmed_txns), 10):
            batch = confirmed_txns[i:i + 10]
            records = []
            for txn in batch:
                records.append({
                    "id": txn.airtable_record_id,
                    "fields": {
                        "Confirmed Code": txn.confirmed_code,
                        "Confirmed Tax Type": txn.confirmed_tax_type,
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

        # Update job status in Airtable
        if job.airtable_record_id:
            try:
                http_requests.patch(
                    f"{base_url}/{AIRTABLE_JOBS_TABLE}/{job.airtable_record_id}",
                    headers=headers,
                    json={"fields": {"Status": "Completed"}},
                    timeout=10,
                )
            except Exception as e:
                logger.error(f"Failed to update job status in Airtable: {e}")

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
    """
    job = get_object_or_404(ReviewJob, pk=pk)
    unconfirmed = job.transactions.filter(is_confirmed=False)

    for txn in unconfirmed:
        txn.confirmed_code = txn.ai_suggested_code
        txn.confirmed_name = txn.ai_suggested_name
        # Auto-suggest tax type based on amount
        if txn.amount > 0:
            txn.confirmed_tax_type = "GST on Income"
        else:
            txn.confirmed_tax_type = "GST on Expenses"
        txn.is_confirmed = True
        txn.save()

    job.confirmed_count = job.transactions.filter(is_confirmed=True).count()
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
