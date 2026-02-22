"""
MCS Platform - Audit Risk & Chart of Accounts Views
Provides the Chart of Accounts management page, Audit Library page,
Risk Engine execution, Risk Flags review, and AI risk analysis.
"""
import json
import hashlib
import logging
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    AccountMapping, ChartOfAccount, RiskRule, RiskReferenceData, RiskFlag,
    FinancialYear, Entity, Client,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------
@login_required
def chart_of_accounts(request):
    """
    Display the MC&S entity-type-specific chart of accounts.
    Grouped by section, with entity type tabs.
    """
    query = request.GET.get("q", "")
    entity_type_filter = request.GET.get("entity_type", "company")
    section_filter = request.GET.get("section", "")

    accounts = ChartOfAccount.objects.filter(
        entity_type=entity_type_filter, is_active=True
    )

    if query:
        accounts = accounts.filter(
            Q(account_code__icontains=query)
            | Q(account_name__icontains=query)
            | Q(classification__icontains=query)
        )

    if section_filter:
        accounts = accounts.filter(section=section_filter)

    accounts = accounts.order_by("section", "display_order")

    # Group by section
    grouped = {}
    for acc in accounts:
        section_label = acc.get_section_display()
        if section_label not in grouped:
            grouped[section_label] = []
        grouped[section_label].append(acc)

    # Get counts per entity type for the tabs
    entity_counts = {}
    for et_value, et_label in Entity.EntityType.choices:
        if et_value == "smsf":
            continue
        entity_counts[et_value] = {
            "label": et_label,
            "count": ChartOfAccount.objects.filter(
                entity_type=et_value, is_active=True
            ).count(),
        }

    context = {
        "grouped_accounts": grouped,
        "total_accounts": ChartOfAccount.objects.filter(
            entity_type=entity_type_filter, is_active=True
        ).count(),
        "total_all": ChartOfAccount.objects.filter(is_active=True).count(),
        "query": query,
        "entity_type_filter": entity_type_filter,
        "section_filter": section_filter,
        "section_choices": ChartOfAccount.StatementSection.choices,
        "entity_counts": entity_counts,
    }
    return render(request, "core/chart_of_accounts.html", context)


@login_required
def chart_of_accounts_api(request):
    """
    JSON API endpoint for chart of accounts.
    Used by the bank statement review page and other AJAX consumers.
    """
    entity_type = request.GET.get("entity_type", "company")
    section = request.GET.get("section", "")
    q = request.GET.get("q", "")

    qs = ChartOfAccount.objects.filter(
        entity_type=entity_type, is_active=True
    ).order_by("section", "display_order")

    if section:
        qs = qs.filter(section=section)
    if q:
        qs = qs.filter(
            Q(account_code__icontains=q) | Q(account_name__icontains=q)
        )

    accounts = [
        {
            "code": a.account_code,
            "name": a.account_name,
            "section": a.get_section_display(),
            "tax": a.tax_code,
            "classification": a.classification,
        }
        for a in qs[:500]
    ]
    return JsonResponse({"accounts": accounts})


# ---------------------------------------------------------------------------
# Audit Library
# ---------------------------------------------------------------------------
@login_required
def audit_library(request):
    """
    Display the audit risk rules library and reference data.
    Shows all configured risk rules with their categories, severity, and status.
    """
    category_filter = request.GET.get("category", "")
    severity_filter = request.GET.get("severity", "")
    query = request.GET.get("q", "")

    rules = RiskRule.objects.all()

    if query:
        rules = rules.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(rule_id__icontains=query)
        )

    if category_filter:
        rules = rules.filter(category=category_filter)

    if severity_filter:
        rules = rules.filter(severity=severity_filter)

    # Group rules by category
    grouped_rules = {}
    for rule in rules:
        cat = rule.get_category_display()
        if cat not in grouped_rules:
            grouped_rules[cat] = []
        grouped_rules[cat].append(rule)

    # Reference data
    reference_data = RiskReferenceData.objects.all()

    # Stats
    total_rules = RiskRule.objects.count()
    active_rules = RiskRule.objects.filter(is_active=True).count()
    total_open_flags = RiskFlag.objects.filter(status="open").count()

    context = {
        "grouped_rules": grouped_rules,
        "reference_data": reference_data,
        "total_rules": total_rules,
        "active_rules": active_rules,
        "total_open_flags": total_open_flags,
        "query": query,
        "category_filter": category_filter,
        "severity_filter": severity_filter,
        "category_choices": RiskRule.Category.choices,
        "severity_choices": RiskRule.Severity.choices,
    }
    return render(request, "core/audit_library.html", context)


# ---------------------------------------------------------------------------
# Run Risk Engine
# ---------------------------------------------------------------------------
@login_required
@require_POST
def run_risk_engine_view(request, pk):
    """
    Trigger the risk engine for a financial year.
    Runs Tier 1 (variance) and Tier 2 (compliance) analysis.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)

    if fy.is_locked:
        messages.warning(request, "Cannot run risk engine on a finalised financial year.")
        return redirect("core:financial_year_detail", pk=pk)

    try:
        from core.risk_engine import run_risk_engine
        results = run_risk_engine(fy, tiers=[1, 2])

        if results["errors"]:
            for err in results["errors"][:5]:
                messages.warning(request, f"Engine warning: {err}")

        flags_msg = f"Risk engine complete: {results['flags_created']} flag(s) raised"
        if results["flags_auto_resolved"] > 0:
            flags_msg += f", {results['flags_auto_resolved']} auto-resolved"

        messages.success(request, flags_msg)

    except Exception as e:
        logger.exception("Risk engine error")
        messages.error(request, f"Risk engine error: {str(e)}")

    return redirect("core:risk_flags", pk=pk)


# ---------------------------------------------------------------------------
# Risk Flags Detail (Enhanced Card-Based UI)
# ---------------------------------------------------------------------------
@login_required
def risk_flags_view(request, pk):
    """
    Show all risk flags for a specific financial year.
    Enhanced card-based layout with filtering by severity, status, tier, and category.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)
    flags = fy.risk_flags.all().order_by("-severity", "-created_at")

    # Filters
    severity_filter = request.GET.get("severity", "")
    status_filter = request.GET.get("status", "")
    tier_filter = request.GET.get("tier", "")
    category_filter = request.GET.get("category", "")

    if severity_filter:
        flags = flags.filter(severity=severity_filter)
    if status_filter:
        flags = flags.filter(status=status_filter)
    if tier_filter:
        flags = flags.filter(tier=int(tier_filter))
    if category_filter:
        # Match by rule category via rule_id prefix or lookup
        rule_ids = RiskRule.objects.filter(category=category_filter).values_list("rule_id", flat=True)
        flags = flags.filter(rule_id__in=rule_ids)

    # Summary counts (unfiltered)
    all_flags = fy.risk_flags.all()
    total_flags_count = all_flags.count()
    open_flags = all_flags.filter(status="open")
    total_open = open_flags.count()

    # Per-severity total counts
    critical_count = all_flags.filter(severity="CRITICAL").count()
    high_count = all_flags.filter(severity="HIGH").count()
    medium_count = all_flags.filter(severity="MEDIUM").count()
    low_count = all_flags.filter(severity="LOW").count()

    # Per-severity open counts
    critical_open = open_flags.filter(severity="CRITICAL").count()
    high_open = open_flags.filter(severity="HIGH").count()
    medium_open = open_flags.filter(severity="MEDIUM").count()
    low_open = open_flags.filter(severity="LOW").count()
    medium_low_open = medium_open + low_open

    # Per-severity resolved counts
    resolved_flags = all_flags.filter(status__in=["resolved", "auto_resolved"])
    resolved_count = resolved_flags.count()
    critical_resolved = resolved_flags.filter(severity="CRITICAL").count()
    high_resolved = resolved_flags.filter(severity="HIGH").count()
    medium_resolved = resolved_flags.filter(severity="MEDIUM").count()
    low_resolved = resolved_flags.filter(severity="LOW").count()

    reviewed_count = all_flags.filter(status="reviewed").count()

    # Progress percentages
    resolution_pct = round((resolved_count / total_flags_count) * 100) if total_flags_count > 0 else 0
    open_pct = 100 - resolution_pct

    # Tier breakdown
    tier1_count = all_flags.filter(tier=1).count()
    tier2_count = all_flags.filter(tier=2).count()
    tier3_count = all_flags.filter(tier=3).count()

    # Category breakdown for filter
    categories_in_use = set()
    for flag in all_flags:
        rule = RiskRule.objects.filter(rule_id=flag.rule_id).first()
        if rule:
            categories_in_use.add((rule.category, rule.get_category_display()))

    # Annotate flags with AI data if available
    flag_list = []
    for flag in flags:
        flag_dict = {
            "flag": flag,
            "ai_explanation": getattr(flag, "ai_explanation", "") or "",
            "ai_suggested_action": getattr(flag, "ai_suggested_action", "") or "",
            "ato_interest_score": getattr(flag, "ato_interest_score", None),
            "has_ai": bool(getattr(flag, "ai_explanation", "")),
        }
        flag_list.append(flag_dict)

    context = {
        "financial_year": fy,
        "entity": fy.entity,
        "flags": flag_list,
        "total_flags": total_flags_count,
        "total_open": total_open,
        # Per-severity totals
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        # Per-severity open
        "critical_open": critical_open,
        "high_open": high_open,
        "medium_open": medium_open,
        "low_open": low_open,
        "medium_low_open": medium_low_open,
        # Per-severity resolved
        "resolved_count": resolved_count,
        "critical_resolved": critical_resolved,
        "high_resolved": high_resolved,
        "medium_resolved": medium_resolved,
        "low_resolved": low_resolved,
        "reviewed_count": reviewed_count,
        # Progress
        "resolution_pct": resolution_pct,
        "open_pct": open_pct,
        # Tier breakdown
        "tier1_count": tier1_count,
        "tier2_count": tier2_count,
        "tier3_count": tier3_count,
        "categories_in_use": sorted(categories_in_use, key=lambda x: x[1]),
        # Current filters
        "severity_filter": severity_filter,
        "status_filter": status_filter,
        "tier_filter": tier_filter,
        "category_filter": category_filter,
    }
    return render(request, "core/risk_flags.html", context)


# ---------------------------------------------------------------------------
# Resolve Risk Flag
# ---------------------------------------------------------------------------
@login_required
@require_POST
def resolve_risk_flag(request, pk):
    """Resolve a single risk flag. Requires minimum 5-word resolution notes."""
    flag = get_object_or_404(RiskFlag, pk=pk)
    resolution_notes = request.POST.get("resolution_notes", "").strip()
    new_status = request.POST.get("new_status", "resolved")

    if new_status == "resolved":
        word_count = len(resolution_notes.split())
        if word_count < 5:
            messages.error(
                request,
                f"Resolution notes must contain at least 5 words (you wrote {word_count}). "
                f"Please describe how this risk was addressed."
            )
            return redirect("core:risk_flags", pk=flag.financial_year.pk)

        flag.status = "resolved"
        flag.resolution_notes = resolution_notes
        flag.resolved_by = request.user
        flag.resolved_at = timezone.now()
        flag.save()
        messages.success(request, f"Risk flag resolved: {flag.title}")

    elif new_status == "reviewed":
        flag.status = "reviewed"
        if resolution_notes:
            flag.resolution_notes = resolution_notes
        flag.save()
        messages.info(request, f"Risk flag marked as reviewed: {flag.title}")

    return redirect("core:risk_flags", pk=flag.financial_year.pk)


# ---------------------------------------------------------------------------
# AI Risk Analysis (Tier 3) — Single Flag
# ---------------------------------------------------------------------------
@login_required
@require_POST
def ai_analyse_flag(request, pk):
    """
    Run AI contextual analysis on a single risk flag.
    Calls Claude API to generate a plain-English explanation and suggested action.
    """
    flag = get_object_or_404(RiskFlag, pk=pk)

    try:
        from core.ai_service import analyse_risk_flag
        result = analyse_risk_flag(flag)

        if result.get("success"):
            flag.ai_explanation = result["explanation"]
            flag.ai_suggested_action = result["suggested_action"]
            flag.ai_data_hash = result.get("data_hash", "")
            flag.save()
            messages.success(request, f"AI analysis complete for: {flag.title}")
        else:
            messages.warning(request, f"AI analysis returned no result: {result.get('error', 'Unknown')}")

    except Exception as e:
        logger.exception("AI analysis error")
        messages.error(request, f"AI analysis error: {str(e)}")

    return redirect("core:risk_flags", pk=flag.financial_year.pk)


# ---------------------------------------------------------------------------
# AI Batch Analysis — All Flags for FY (uses batch_analyse_flags)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def ai_analyse_all_flags(request, pk):
    """
    Run batch AI analysis on all open flags for a financial year.
    Uses the batch engine with caching and materiality-aware prompts.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)
    force = request.POST.get("force", "") == "1"

    try:
        from core.ai_service import batch_analyse_flags
        result = batch_analyse_flags(fy, force=force)

        if result.get("success"):
            msg = f"AI batch analysis complete: {result['analysed']} analysed"
            if result.get('skipped'):
                msg += f", {result['skipped']} cached (skipped)"
            if result.get('errors'):
                msg += f", {result['errors']} error(s)"
            messages.success(request, msg)
        else:
            messages.warning(request, "Batch analysis returned no results.")

    except Exception as e:
        logger.exception("AI batch analysis error")
        messages.error(request, f"AI batch analysis error: {str(e)}")

    return redirect("core:risk_flags", pk=pk)


# ---------------------------------------------------------------------------
# AI Feedback — Record user corrections on AI analysis
# ---------------------------------------------------------------------------
@login_required
@require_POST
def ai_feedback_view(request, pk):
    """
    Record user feedback on an AI analysis result.
    Stores the feedback for future prompt improvement.
    """
    flag = get_object_or_404(RiskFlag, pk=pk)
    feedback_type = request.POST.get("feedback_type", "")
    user_notes = request.POST.get("feedback_notes", "").strip()

    valid_types = ["correct", "partially_correct", "incorrect", "irrelevant"]
    if feedback_type not in valid_types:
        messages.error(request, "Invalid feedback type.")
        return redirect("core:risk_flags", pk=flag.financial_year.pk)

    try:
        from core.ai_service import record_feedback
        record_feedback(flag, feedback_type, user_notes, request.user)
        messages.success(request, f"Feedback recorded for: {flag.title}")
    except Exception as e:
        logger.exception("AI feedback error")
        messages.error(request, f"Error recording feedback: {str(e)}")

    return redirect("core:risk_flags", pk=flag.financial_year.pk)


# ---------------------------------------------------------------------------
# AI Smart Flag Prioritisation
# ---------------------------------------------------------------------------
@login_required
@require_POST
def ai_prioritise_flags(request, pk):
    """
    Run AI prioritisation to score flags by 'Likely ATO Interest'.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)
    flags = fy.risk_flags.filter(status__in=["open", "reviewed"])

    try:
        from core.ai_service import prioritise_flags
        result = prioritise_flags(list(flags), fy)

        if result.get("success"):
            scored = result.get("scored", 0)
            messages.success(request, f"AI prioritisation complete: {scored} flag(s) scored.")
        else:
            messages.warning(request, f"Prioritisation issue: {result.get('error', 'Unknown')}")

    except Exception as e:
        logger.exception("AI prioritisation error")
        messages.error(request, f"AI prioritisation error: {str(e)}")

    return redirect("core:risk_flags", pk=pk)


# ---------------------------------------------------------------------------
# Generate AI Risk Summary Report
# ---------------------------------------------------------------------------
@login_required
def generate_risk_report(request, pk):
    """
    Generate a narrative AI Risk Summary Report in Word format.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)

    try:
        from core.ai_service import generate_risk_summary_report
        doc_bytes = generate_risk_summary_report(fy)

        response = HttpResponse(
            doc_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        filename = f"Risk_Summary_{fy.entity.entity_name}_{fy.year_label}.docx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        logger.exception("Risk report generation error")
        messages.error(request, f"Report generation error: {str(e)}")
        return redirect("core:risk_flags", pk=pk)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_flag_hash(flag):
    """Compute a hash of the flag's data for AI cache invalidation."""
    data_str = json.dumps({
        "rule_id": flag.rule_id,
        "severity": flag.severity,
        "description": flag.description,
        "calculated_values": flag.calculated_values,
        "affected_accounts": flag.affected_accounts,
    }, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()
