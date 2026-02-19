"""
Bank Statement Review views.

Provides the dashboard (pending reviews + activity feed), the transaction
review page, and API endpoints for the n8n webhook and transaction submission.

Enhanced with GST handling, learning feedback, and bank statement upload.
"""
import json
import logging
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import PendingTransaction, ReviewActivity, ReviewJob, TransactionPattern

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

            first_fields = records[0].get("fields", {})
            accountant_email = first_fields.get("Accountant Email", "")

            confirmed_count = sum(1 for s in statuses if s == "Confirmed")

            # Try to match entity for GST status
            from core.models import Entity
            entity = None
            is_gst = True
            try:
                entity = Entity.objects.filter(
                    entity_name__icontains=client_name
                ).first()
                if entity:
                    is_gst = entity.is_gst_registered
            except Exception:
                pass

            # Create or update the ReviewJob
            job, created = ReviewJob.objects.update_or_create(
                client_name=client_name,
                status__in=["awaiting_review", "in_progress"],
                defaults={
                    "entity": entity,
                    "file_name": f"Bank Statement — {len(records)} transactions",
                    "submitted_by": accountant_email or "Via bankstatements@mcands.com.au",
                    "source": "airtable",
                    "total_transactions": len(records),
                    "auto_coded_count": len(records),
                    "flagged_count": len(records),
                    "confirmed_count": confirmed_count,
                    "status": job_status,
                    "is_gst_registered": is_gst,
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
                amount = Decimal(str(fields.get("Amount", 0)))
                tax_type = fields.get("AI Suggested Tax Type", "")

                # Calculate GST
                abs_amount = abs(amount)
                if is_gst and tax_type in ("GST on Income", "GST on Expenses"):
                    gst_amount = (abs_amount / Decimal("11")).quantize(Decimal("0.01"))
                    net_amount = (abs_amount - gst_amount).quantize(Decimal("0.01"))
                else:
                    gst_amount = Decimal("0.00")
                    net_amount = abs_amount

                PendingTransaction.objects.update_or_create(
                    airtable_record_id=rec["id"],
                    defaults={
                        "job": job,
                        "date": fields.get("Transaction Date", ""),
                        "description": fields.get("Description", ""),
                        "amount": amount,
                        "gst_amount": gst_amount,
                        "net_amount": net_amount,
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
    Dashboard view showing audit risk alerts, pending reviews,
    unfinalised client files, and recent activity.
    """
    from core.models import (
        Client, Entity, FinancialYear, RiskFlag, AuditLog,
    )
    from django.db.models import Q, Count

    # Sync from Airtable if configured
    if _airtable_configured():
        _sync_from_airtable()

    # --- Pending bank statement reviews ---
    pending_jobs = ReviewJob.objects.filter(
        status__in=["awaiting_review", "in_progress"]
    ).order_by("-received_at")

    completed_jobs = ReviewJob.objects.filter(
        status="completed"
    ).order_by("-completed_at")[:5]

    activities = ReviewActivity.objects.all().order_by("-created_at")[:10]

    # Learning stats
    total_patterns = TransactionPattern.objects.count()

    # --- Audit Risk Alerts ---
    # Get clients that have open risk flags, grouped by client with severity counts
    user = request.user
    if user.is_admin:
        client_qs = Client.objects.filter(is_active=True)
    else:
        client_qs = Client.objects.filter(
            Q(assigned_accountant=user) & Q(is_active=True)
        )

    # Find financial years with open risk flags
    flagged_years = (
        FinancialYear.objects.filter(
            entity__client__in=client_qs,
            risk_flags__status="open",
        )
        .select_related("entity", "entity__client")
        .distinct()
    )

    risk_alerts = []
    for fy in flagged_years:
        open_flags = fy.risk_flags.filter(status="open")
        high_count = open_flags.filter(severity__in=["HIGH", "CRITICAL"]).count()
        medium_count = open_flags.filter(severity="MEDIUM").count()
        low_count = open_flags.filter(severity="LOW").count()
        total_flags = open_flags.count()
        if total_flags > 0:
            risk_alerts.append({
                "client_name": fy.entity.entity_name,
                "entity_name": fy.entity.entity_name,
                "year_label": fy.year_label,
                "financial_year": fy,
                "high_count": high_count,
                "medium_count": medium_count,
                "low_count": low_count,
                "total_flags": total_flags,
            })
    # Sort by high count descending
    risk_alerts.sort(key=lambda x: (x["high_count"], x["total_flags"]), reverse=True)

    # --- Unfinalised Client Files ---
    unfinalised_years = (
        FinancialYear.objects.filter(
            entity__client__in=client_qs,
            status__in=["draft", "in_review", "reviewed"],
        )
        .select_related("entity", "entity__client")
        .order_by("-end_date")[:10]
    )

    # --- Recent Activity (from AuditLog) ---
    recent_audit_logs = AuditLog.objects.all().order_by("-timestamp")[:10]

    # --- Time-based greeting (Melbourne time) ---
    from datetime import datetime
    import zoneinfo
    now = datetime.now(zoneinfo.ZoneInfo("Australia/Melbourne"))
    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    first_name = request.user.first_name or request.user.username.capitalize()

    # --- Entity list for upload modal ---
    entities = Entity.objects.filter(
        client__in=client_qs
    ).select_related("client").order_by("entity_name")

    context = {
        "greeting": greeting,
        "first_name": first_name,
        "pending_jobs": pending_jobs,
        "completed_jobs": completed_jobs,
        "activities": activities,
        "total_patterns": total_patterns,
        "risk_alerts": risk_alerts,
        "unfinalised_years": unfinalised_years,
        "recent_audit_logs": recent_audit_logs,
        "entities": entities,
    }
    return render(request, "review/dashboard.html", context)


@login_required
def review_detail(request, pk):
    """
    Transaction review page for a specific job.
    Shows all flagged transactions with account picker, tax type dropdowns,
    and GST breakdown columns for GST-registered entities.
    """
    job = get_object_or_404(ReviewJob, pk=pk)
    transactions = job.transactions.all().order_by("date", "description")

    # Get entity-type-specific chart of accounts for the picker
    from core.models import ChartOfAccount
    entity_type = job.entity.entity_type if job.entity else "company"
    coa_qs = ChartOfAccount.objects.filter(
        entity_type=entity_type, is_active=True
    ).order_by("section", "display_order")
    accounts = [
        {
            "code": a.account_code,
            "name": a.account_name,
            "section": a.get_section_display(),
            "tax": a.tax_code,
        }
        for a in coa_qs
    ]

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
    Recalculates GST based on confirmed tax type.
    Updates the local record and pushes to Airtable.
    """
    txn = get_object_or_404(PendingTransaction, pk=pk)
    data = json.loads(request.body)

    txn.confirmed_code = data.get("confirmed_code", "")
    txn.confirmed_name = data.get("confirmed_name", "")
    txn.confirmed_tax_type = data.get("confirmed_tax_type", "")
    txn.is_confirmed = True

    # Recalculate GST based on confirmed tax type
    is_gst = txn.job.is_gst_registered
    txn.calculate_gst(tax_type=txn.confirmed_tax_type, is_gst_registered=is_gst)
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
        "gst_amount": str(txn.gst_amount),
        "net_amount": str(txn.net_amount),
    })


@login_required
@require_POST
def submit_review(request, pk):
    """
    Submit all confirmed transactions for a job.
    Saves patterns to the learning database.
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

    # Save patterns to learning database
    from .learning import save_patterns_from_job, push_pattern_to_airtable
    patterns_saved = save_patterns_from_job(job)

    # Batch update Airtable
    headers = _get_airtable_headers()
    if headers:
        import requests as http_requests
        base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

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
        description=(
            f"{job.client_name} — {job.confirmed_count} transactions confirmed, "
            f"{patterns_saved} patterns learned"
        ),
    )

    return JsonResponse({"status": "ok", "redirect": "/"})


@login_required
@require_POST
def accept_all_suggestions(request, pk):
    """
    Accept all AI suggestions for unconfirmed transactions in a job.
    Calculates GST based on the suggested tax type.
    """
    job = get_object_or_404(ReviewJob, pk=pk)
    unconfirmed = job.transactions.filter(is_confirmed=False)
    is_gst = job.is_gst_registered

    for txn in unconfirmed:
        txn.confirmed_code = txn.ai_suggested_code
        txn.confirmed_name = txn.ai_suggested_name
        # Use AI suggested tax type if available
        if txn.ai_suggested_tax_type:
            txn.confirmed_tax_type = txn.ai_suggested_tax_type
        elif not is_gst:
            txn.confirmed_tax_type = "BAS Excluded"
        elif txn.amount > 0:
            txn.confirmed_tax_type = "GST on Income"
        else:
            txn.confirmed_tax_type = "GST on Expenses"

        # Recalculate GST
        txn.calculate_gst(tax_type=txn.confirmed_tax_type, is_gst_registered=is_gst)
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
# Bank Statement Upload (manual PDF/Excel upload)
# ---------------------------------------------------------------------------

@login_required
def upload_bank_statement(request):
    """
    Handle manual bank statement upload (PDF or Excel).
    Processes through the same pipeline as email ingestion.
    Accepts period_start and period_end to filter out-of-period transactions.
    Supports multiple files via 'files' field.
    """
    from datetime import datetime as dt
    from .pdf_parsers import extract_transactions_from_pdf_direct

    # Support both single 'file' and multiple 'files' field names
    uploaded_files = request.FILES.getlist("files")
    if not uploaded_files:
        single = request.FILES.get("file")
        if single:
            uploaded_files = [single]

    entity_id = request.POST.get("entity_id")
    client_name = request.POST.get("client_name", "Unknown")
    period_start_str = request.POST.get("period_start", "")
    period_end_str = request.POST.get("period_end", "")
    user_opening_balance_str = request.POST.get("opening_balance", "")
    financial_year_id = request.POST.get("financial_year_id", "")

    if not uploaded_files:
        return JsonResponse({"status": "error", "message": "No files uploaded"}, status=400)
    # Parse period dates
    period_start_date = None
    period_end_date = None
    try:
        if period_start_str:
            period_start_date = dt.strptime(period_start_str, "%Y-%m-%d").date()
        if period_end_str:
            period_end_date = dt.strptime(period_end_str, "%Y-%m-%d").date()
    except ValueError:
        pass

    # Get entity for GST status
    entity = None
    is_gst = True
    if entity_id:
        from core.models import Entity
        try:
            entity = Entity.objects.get(pk=entity_id)
            is_gst = entity.is_gst_registered
            client_name = entity.entity_name
        except Exception:
            pass

    # Process each uploaded file
    created_jobs = []
    errors = []

    for uploaded_file in uploaded_files:
        content = uploaded_file.read()
        filename = uploaded_file.name
        logger.info(f"Processing file: {filename} ({len(content)} bytes)")

        try:
            if filename.lower().endswith(".pdf"):
                extracted = extract_transactions_from_pdf_direct(content, filename)
            else:
                extracted = _parse_excel_bank_statement(content, filename)
        except Exception as exc:
            logger.error(f"Extraction exception for {filename}: {exc}", exc_info=True)
            errors.append(f"{filename}: Extraction error — {exc}")
            continue

        logger.info(f"Extraction result for {filename}: {type(extracted)} — keys={list(extracted.keys()) if isinstance(extracted, dict) else 'N/A'} — txn_count={len(extracted.get('transactions', [])) if isinstance(extracted, dict) else 0}")

        if not extracted or not extracted.get("transactions"):
            errors.append(f"{filename}: No transactions could be extracted")
            continue

        transactions = extracted["transactions"]

        # Filter transactions by period if dates were provided
        if period_start_date or period_end_date:
            filtered = []
            excluded_count = 0
            for txn in transactions:
                txn_date_str = txn.get("date", "")
                txn_date = None
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
                    try:
                        txn_date = dt.strptime(txn_date_str.strip(), fmt).date()
                        break
                    except (ValueError, AttributeError):
                        continue

                if txn_date:
                    if period_start_date and txn_date < period_start_date:
                        excluded_count += 1
                        continue
                    if period_end_date and txn_date > period_end_date:
                        excluded_count += 1
                        continue

                filtered.append(txn)

            logger.info(
                f"Period filter ({filename}): {len(transactions)} total, {len(filtered)} in period, "
                f"{excluded_count} excluded ({period_start_str} to {period_end_str})"
            )
            transactions = filtered

        if not transactions:
            errors.append(f"{filename}: No transactions within the selected period")
            continue

        # Save transactions WITHOUT classification (fast)
        # Classification happens asynchronously on the review page
        logger.info(f"Creating ReviewJob for {filename} with {len(transactions)} transactions (no classification)")

        # Create ReviewJob
        # Determine opening balance: user-entered takes priority, then extracted from file
        extracted_opening = Decimal(str(extracted.get("opening_balance", 0)))
        if user_opening_balance_str:
            try:
                user_opening_balance = Decimal(user_opening_balance_str)
            except Exception:
                user_opening_balance = extracted_opening
        else:
            user_opening_balance = extracted_opening

        job = ReviewJob.objects.create(
            entity=entity,
            client_name=client_name,
            file_name=filename,
            submitted_by=request.user.get_full_name() or request.user.username,
            source="upload",
            total_transactions=len(transactions),
            auto_coded_count=0,
            flagged_count=len(transactions),
            confirmed_count=0,
            is_gst_registered=is_gst,
            bank_account_name=extracted.get("account_name", ""),
            bsb=extracted.get("bsb", ""),
            account_number=extracted.get("account_number", ""),
            period_start=period_start_str or extracted.get("period_start", ""),
            period_end=period_end_str or extracted.get("period_end", ""),
            opening_balance=user_opening_balance,
            closing_balance=Decimal(str(extracted.get("closing_balance", 0))),
        )

        # Create PendingTransactions - unclassified (bulk for speed)
        pending_objs = []
        for txn in transactions:
            amount = Decimal(str(txn.get("amount", 0)))
            abs_amount = abs(amount)
            pending_objs.append(PendingTransaction(
                job=job,
                date=txn.get("date", ""),
                description=txn.get("description", ""),
                amount=amount,
                gst_amount=Decimal("0.00"),
                net_amount=abs_amount,
                ai_suggested_code="",
                ai_suggested_name="",
                ai_suggested_tax_type="",
                ai_confidence=0,
                ai_reasoning="",
                from_learning=False,
                is_confirmed=False,
                confirmed_code="",
                confirmed_name="",
                confirmed_tax_type="",
            ))
        PendingTransaction.objects.bulk_create(pending_objs)
        logger.info(f"Created {len(pending_objs)} PendingTransactions for job {job.pk}")

        # Cross-check opening balance against trial balance
        balance_warning = None
        if user_opening_balance and user_opening_balance != Decimal('0') and entity and financial_year_id:
            try:
                from core.models import FinancialYear, TrialBalanceLine
                fy = FinancialYear.objects.get(pk=financial_year_id)
                # Look for bank account lines in the trial balance (common codes: 1-xxxx for bank accounts)
                bank_tb_lines = TrialBalanceLine.objects.filter(
                    financial_year=fy,
                    account_code__regex=r'^1-[0-9]',  # Bank accounts typically start with 1-
                )
                if bank_tb_lines.exists():
                    tb_bank_total = sum(line.net_movement for line in bank_tb_lines)
                    difference = abs(user_opening_balance - tb_bank_total)
                    if difference > Decimal('0.01'):
                        balance_warning = (
                            f"BALANCE MISMATCH: Opening balance entered (${user_opening_balance:,.2f}) "
                            f"differs from trial balance bank total (${tb_bank_total:,.2f}) "
                            f"by ${difference:,.2f}. Please investigate — you may have missed a bank statement."
                        )
                        logger.warning(f"Balance mismatch for {client_name}: {balance_warning}")
                        # Create a risk flag if the model exists
                        try:
                            from core.models import RiskFlag
                            RiskFlag.objects.create(
                                financial_year=fy,
                                severity='MEDIUM',
                                category='bank_reconciliation',
                                title='Bank balance mismatch detected',
                                description=balance_warning,
                                status='open',
                            )
                        except Exception as e:
                            logger.error(f"Could not create risk flag: {e}")
                else:
                    # No bank lines in TB yet — store the opening balance as the reference point
                    logger.info(f"No bank lines in TB for {client_name}. Opening balance ${user_opening_balance:,.2f} will be the reference.")
            except Exception as e:
                logger.error(f"Balance cross-check error: {e}")

        # Log activity
        activity_desc = (
            f"{client_name} — {len(transactions)} transactions from {filename}, "
            f"{job.confirmed_count} auto-confirmed"
            f"{'  (GST registered)' if is_gst else ' (not GST registered)'}"
        )
        if balance_warning:
            activity_desc += f" | WARNING: {balance_warning}"

        ReviewActivity.objects.create(
            activity_type="new_statement",
            title="Bank statement uploaded",
            description=activity_desc,
        )
        # Dashboard activity log
        try:
            from core.models import ActivityLog
            ActivityLog.objects.create(
                user=request.user,
                event_type="bank_upload",
                title=f"Bank statement uploaded: {filename}",
                description=f"{client_name} — {len(transactions)} transactions extracted",
                url=f"/review/{job.pk}/",
            )
        except Exception:
            pass
        created_jobs.append(job)

    # Handle response
    logger.info(f"Upload complete: {len(created_jobs)} jobs created, {len(errors)} errors. Sending response.")
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not created_jobs:
        error_msg = "; ".join(errors) if errors else "No transactions could be extracted from any file"
        if is_ajax:
            return JsonResponse({"status": "error", "message": error_msg}, status=400)
        from django.contrib import messages as django_messages
        django_messages.error(request, error_msg)
        return redirect("review:dashboard")

    # Build redirect URL — go back to the financial year page (review tab) so user stays in context
    from django.urls import reverse
    from django.contrib import messages as django_messages

    # Collect any balance warnings from all jobs
    all_balance_warnings = []
    for j in created_jobs:
        if hasattr(j, '_balance_warning') and j._balance_warning:
            all_balance_warnings.append(j._balance_warning)

    if financial_year_id:
        redirect_url = reverse("core:financial_year_detail", kwargs={"pk": financial_year_id}) + "#tab-review"
    elif len(created_jobs) == 1:
        redirect_url = reverse("review:review_detail", kwargs={"pk": created_jobs[0].pk})
    else:
        redirect_url = reverse("review:dashboard")

    success_msg = (
        f"Successfully processed {len(created_jobs)} bank statement(s) "
        f"({sum(j.total_transactions for j in created_jobs)} total transactions)."
    )
    if errors:
        success_msg += f" Errors: {'; '.join(errors)}"
    django_messages.success(request, success_msg)

    # Show balance warning as a separate warning message
    if balance_warning:
        django_messages.warning(request, balance_warning)

    if is_ajax:
        return JsonResponse({
            "status": "success",
            "redirect": redirect_url,
            "jobs_created": len(created_jobs),
            "total_transactions": sum(j.total_transactions for j in created_jobs),
            "errors": errors,
            "balance_warning": balance_warning,
        })
    return redirect(redirect_url)


def _parse_excel_bank_statement(content, filename):
    """Parse an Excel/CSV bank statement into the standard transaction format."""
    import io
    try:
        import pandas as pd
    except ImportError:
        return None

    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        # Try to identify columns
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if "date" in col_lower:
                col_map["date"] = col
            elif "desc" in col_lower or "narr" in col_lower or "particular" in col_lower:
                col_map["description"] = col
            elif "amount" in col_lower or "value" in col_lower:
                col_map["amount"] = col
            elif "debit" in col_lower:
                col_map["debit"] = col
            elif "credit" in col_lower:
                col_map["credit"] = col

        transactions = []
        for _, row in df.iterrows():
            date = str(row.get(col_map.get("date", ""), ""))
            desc = str(row.get(col_map.get("description", ""), ""))

            if "amount" in col_map:
                amount = float(row.get(col_map["amount"], 0) or 0)
            elif "debit" in col_map and "credit" in col_map:
                debit = float(row.get(col_map["debit"], 0) or 0)
                credit = float(row.get(col_map["credit"], 0) or 0)
                amount = credit - debit
            else:
                continue

            if desc and desc != "nan":
                transactions.append({
                    "date": date,
                    "description": desc,
                    "amount": amount,
                })

        return {
            "transactions": transactions,
            "opening_balance": 0,
            "closing_balance": 0,
            "account_name": "",
            "bsb": "",
            "account_number": "",
            "period_start": "",
            "period_end": "",
        }
    except Exception as e:
        logger.error(f"Excel parsing failed: {e}")
        return None


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

        # Try to match entity
        from core.models import Entity
        entity = None
        is_gst = True
        client_name = data.get("client_name", "Unknown")
        try:
            entity = Entity.objects.filter(
                entity_name__icontains=client_name
            ).first()
            if entity:
                is_gst = entity.is_gst_registered
        except Exception:
            pass

        job = ReviewJob.objects.create(
            airtable_record_id=data.get("airtable_record_id"),
            entity=entity,
            client_name=client_name,
            file_name=data.get("file_name", ""),
            submitted_by=data.get("submitted_by", ""),
            source="airtable",
            total_transactions=data.get("total_transactions", 0),
            auto_coded_count=data.get("auto_coded_count", 0),
            flagged_count=data.get("flagged_count", 0),
            is_gst_registered=is_gst,
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


# ---------------------------------------------------------------------------
# Async Classification (AJAX endpoint)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def classify_batch(request, pk):
    """
    AJAX endpoint to classify a batch of unclassified transactions for a job.
    Called repeatedly from the review page to classify in small batches.

    POST /api/review/<pk>/classify-batch/
    Body: {"batch_size": 15}  (optional, defaults to 15)

    Returns:
    {
        "status": "ok",
        "classified": [...],  // list of {txn_id, code, name, tax_type, confidence, reasoning}
        "remaining": int,     // how many unclassified transactions remain
        "total": int,
        "auto_coded_count": int,
    }
    """
    from .email_ingestion import classify_transactions

    job = get_object_or_404(ReviewJob, pk=pk)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    batch_size = min(int(data.get("batch_size", 15)), 30)  # Cap at 30

    # Get unclassified transactions (ai_confidence == 0 and no ai_suggested_code)
    unclassified = list(
        job.transactions.filter(ai_confidence=0, ai_suggested_code="")
        .order_by("date", "description")[:batch_size]
    )

    if not unclassified:
        return JsonResponse({
            "status": "ok",
            "classified": [],
            "remaining": 0,
            "total": job.total_transactions,
            "auto_coded_count": job.auto_coded_count,
        })

    # Build transaction dicts for the classifier
    txn_dicts = [
        {
            "date": txn.date,
            "description": txn.description,
            "amount": float(txn.amount),
        }
        for txn in unclassified
    ]

    entity = job.entity
    is_gst = job.is_gst_registered

    try:
        classifications = classify_transactions(
            txn_dicts, entity=entity, is_gst_registered=is_gst
        )
    except Exception as exc:
        logger.error(f"classify_batch failed for job {pk}: {exc}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": f"Classification error: {str(exc)}",
        }, status=500)

    # Update each transaction with its classification
    classified_results = []
    for txn, cls in zip(unclassified, classifications):
        if cls is None:
            cls = {
                "account_code": "0000",
                "account_name": "Suspense",
                "tax_type": "N-T",
                "confidence": 1,
                "reasoning": "",
                "from_learning": False,
            }

        txn.ai_suggested_code = cls.get("account_code", "0000")
        txn.ai_suggested_name = cls.get("account_name", "Suspense")
        txn.ai_suggested_tax_type = cls.get("tax_type", "")
        txn.ai_confidence = cls.get("confidence", 1)
        txn.ai_reasoning = cls.get("reasoning", "")
        txn.from_learning = cls.get("from_learning", False)

        # Calculate GST
        tax_type = cls.get("tax_type", "")
        abs_amount = abs(txn.amount)
        if is_gst and tax_type in ("GST on Income", "GST on Expenses"):
            txn.gst_amount = (abs_amount / Decimal("11")).quantize(Decimal("0.01"))
            txn.net_amount = (abs_amount - txn.gst_amount).quantize(Decimal("0.01"))
        else:
            txn.gst_amount = Decimal("0.00")
            txn.net_amount = abs_amount

        # Auto-confirm if from learning with high confidence
        is_auto_confirmed = (
            cls.get("from_learning", False) and cls.get("confidence", 0) >= 5
        )
        if is_auto_confirmed:
            txn.is_confirmed = True
            txn.confirmed_code = txn.ai_suggested_code
            txn.confirmed_name = txn.ai_suggested_name
            txn.confirmed_tax_type = tax_type

        txn.save()

        classified_results.append({
            "txn_id": str(txn.pk),
            "code": txn.ai_suggested_code,
            "name": txn.ai_suggested_name,
            "tax_type": txn.ai_suggested_tax_type,
            "confidence": txn.ai_confidence,
            "reasoning": txn.ai_reasoning,
            "from_learning": txn.from_learning,
            "gst_amount": str(txn.gst_amount),
            "net_amount": str(txn.net_amount),
            "is_confirmed": txn.is_confirmed,
        })

    # Update job counts
    job.auto_coded_count = job.transactions.exclude(
        ai_confidence=0, ai_suggested_code=""
    ).count()
    job.confirmed_count = job.transactions.filter(is_confirmed=True).count()
    if job.confirmed_count > 0 and job.status == "awaiting_review":
        job.status = "in_progress"
    job.save()

    remaining = job.transactions.filter(
        ai_confidence=0, ai_suggested_code=""
    ).count()

    # Log activity when ALL classification is complete (remaining == 0)
    if remaining == 0:
        try:
            from core.models import ActivityLog
            client_name = job.entity.entity_name if job.entity else job.client_name
            ActivityLog.objects.create(
                user=request.user,
                event_type="classify_complete",
                title=f"AI classification complete: {client_name}",
                description=f"{job.total_transactions} transactions classified, {job.confirmed_count} auto-confirmed",
                url=f"/review/{job.pk}/",
            )
        except Exception:
            pass

    return JsonResponse({
        "status": "ok",
        "classified": classified_results,
        "remaining": remaining,
        "total": job.total_transactions,
        "auto_coded_count": job.auto_coded_count,
        "confirmed_count": job.confirmed_count,
    })
