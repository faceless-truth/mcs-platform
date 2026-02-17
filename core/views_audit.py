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
    AccountMapping, RiskRule, RiskReferenceData, RiskFlag,
    FinancialYear, Entity, Client,
)


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------
@login_required
def chart_of_accounts(request):
    """
    Display the MC&S standard chart of accounts (AccountMapping).
    Grouped by financial statement and section.
    """
    query = request.GET.get("q", "")
    statement_filter = request.GET.get("statement", "")

    accounts = AccountMapping.objects.all()

    if query:
        accounts = accounts.filter(
            Q(standard_code__icontains=query)
            | Q(line_item_label__icontains=query)
            | Q(statement_section__icontains=query)
        )

    if statement_filter:
        accounts = accounts.filter(financial_statement=statement_filter)

    # Group by financial statement then section
    grouped = {}
    for acc in accounts:
        stmt = acc.get_financial_statement_display()
        section = acc.statement_section
        if stmt not in grouped:
            grouped[stmt] = {}
        if section not in grouped[stmt]:
            grouped[stmt][section] = []
        grouped[stmt][section].append(acc)

    context = {
        "grouped_accounts": grouped,
        "total_accounts": AccountMapping.objects.count(),
        "query": query,
        "statement_filter": statement_filter,
        "statement_choices": AccountMapping.FinancialStatement.choices,
    }
    return render(request, "core/chart_of_accounts.html", context)


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
    """Resolve a single risk flag."""
    flag = get_object_or_404(RiskFlag, pk=pk)
    flag.status = "resolved"
    flag.resolution_notes = request.POST.get("resolution_notes", "")
    flag.resolved_by = request.user
    flag.resolved_at = timezone.now()
    flag.save()
    messages.success(request, f"Risk flag resolved: {flag.title}")
    return redirect("core:risk_flags", pk=flag.financial_year.pk)
