"""
MCS Platform - Audit Risk & Chart of Accounts Views
Provides the Chart of Accounts management page and Audit Library page.
"""
import json
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
            continue  # SMSF doesn't have its own chart
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
# Risk Flags Detail (for a specific financial year)
# ---------------------------------------------------------------------------
@login_required
def risk_flags_view(request, pk):
    """
    Show all risk flags for a specific financial year.
    Allows reviewing and resolving flags.
    """
    fy = get_object_or_404(FinancialYear, pk=pk)
    flags = fy.risk_flags.all().order_by("-severity", "-created_at")

    severity_filter = request.GET.get("severity", "")
    status_filter = request.GET.get("status", "")

    if severity_filter:
        flags = flags.filter(severity=severity_filter)
    if status_filter:
        flags = flags.filter(status=status_filter)

    # Summary counts
    open_flags = fy.risk_flags.filter(status="open")
    high_count = open_flags.filter(severity__in=["HIGH", "CRITICAL"]).count()
    medium_count = open_flags.filter(severity="MEDIUM").count()
    low_count = open_flags.filter(severity="LOW").count()

    context = {
        "financial_year": fy,
        "flags": flags,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "total_open": open_flags.count(),
        "severity_filter": severity_filter,
        "status_filter": status_filter,
    }
    return render(request, "core/risk_flags.html", context)


@login_required
@require_POST
def resolve_risk_flag(request, pk):
    """Resolve a single risk flag. Requires minimum 5-word resolution notes."""
    flag = get_object_or_404(RiskFlag, pk=pk)
    resolution_notes = request.POST.get("resolution_notes", "").strip()

    # Require minimum 5 words in the resolution notes
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
    return redirect("core:risk_flags", pk=flag.financial_year.pk)
