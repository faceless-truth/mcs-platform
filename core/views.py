"""MCS Platform - Core Views"""
import openpyxl
from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import (
    Client, Entity, FinancialYear, TrialBalanceLine,
    AccountMapping, ChartOfAccount, ClientAccountMapping, AdjustingJournal,
    JournalLine, GeneratedDocument, AuditLog, EntityOfficer,
    ClientAssociate, AccountingSoftware, MeetingNote,
)
from .forms import (
    ClientForm, EntityForm, FinancialYearForm,
    TrialBalanceUploadForm, AccountMappingForm,
    AdjustingJournalForm, JournalLineFormSet,
    EntityOfficerForm, ClientAssociateForm, AccountingSoftwareForm,
    MeetingNoteForm,
)


def _log_action(request, action, description, obj=None):
    """Create an audit log entry."""
    AuditLog.objects.create(
        user=request.user,
        action=action,
        description=description,
        affected_object_type=type(obj).__name__ if obj else "",
        affected_object_id=str(obj.pk) if obj else "",
        ip_address=request.META.get("REMOTE_ADDR"),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    user = request.user
    if user.is_admin:
        clients = Client.objects.filter(is_active=True)
    else:
        clients = Client.objects.filter(
            Q(assigned_accountant=user) & Q(is_active=True)
        )

    # Summary stats
    total_clients = clients.count()
    total_entities = Entity.objects.filter(client__in=clients).count()
    draft_count = FinancialYear.objects.filter(
        entity__client__in=clients, status="draft"
    ).count()
    in_review_count = FinancialYear.objects.filter(
        entity__client__in=clients, status="in_review"
    ).count()
    finalised_count = FinancialYear.objects.filter(
        entity__client__in=clients, status="finalised"
    ).count()

    # Recent activity
    recent_years = (
        FinancialYear.objects.filter(entity__client__in=clients)
        .select_related("entity", "entity__client")
        .order_by("-updated_at")[:10]
    )

    context = {
        "total_clients": total_clients,
        "total_entities": total_entities,
        "draft_count": draft_count,
        "in_review_count": in_review_count,
        "finalised_count": finalised_count,
        "recent_years": recent_years,
    }
    return render(request, "core/dashboard.html", context)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@login_required
def client_list(request):
    query = request.GET.get("q", "")
    entity_type = request.GET.get("entity_type", "")
    status_filter = request.GET.get("status", "")

    if request.user.is_admin:
        clients = Client.objects.filter(is_active=True)
    else:
        clients = Client.objects.filter(
            assigned_accountant=request.user, is_active=True
        )

    if query:
        clients = clients.filter(
            Q(name__icontains=query)
            | Q(entities__abn__icontains=query)
            | Q(entities__entity_name__icontains=query)
        ).distinct()

    clients = clients.annotate(num_entities=Count("entities"))

    context = {
        "clients": clients,
        "query": query,
        "entity_type": entity_type,
        "status_filter": status_filter,
    }

    if request.htmx:
        return render(request, "partials/client_list_rows.html", context)
    return render(request, "core/client_list.html", context)


@login_required
def client_create(request):
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to create clients.")
        return redirect("review:dashboard")

    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            _log_action(request, "import", f"Created client: {client.name}", client)
            messages.success(request, f"Client '{client.name}' created successfully.")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = ClientForm()
    return render(request, "core/client_form.html", {"form": form, "title": "Create Client"})


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    entities = client.entities.all()
    associates = client.associates.filter(is_active=True)
    family_associates = [a for a in associates if a.is_family]
    business_associates = [a for a in associates if not a.is_family]
    software_configs = client.software_configs.all()
    meeting_notes = client.meeting_notes.all()[:20]
    pending_followups = client.meeting_notes.filter(
        follow_up_completed=False, follow_up_date__isnull=False
    ).order_by("follow_up_date")
    context = {
        "client": client,
        "entities": entities,
        "family_associates": family_associates,
        "business_associates": business_associates,
        "software_configs": software_configs,
        "meeting_notes": meeting_notes,
        "pending_followups": pending_followups,
    }
    return render(request, "core/client_detail.html", context)


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to edit clients.")
        return redirect("core:client_detail", pk=pk)

    if request.method == "POST":
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, f"Client '{client.name}' updated.")
            return redirect("core:client_detail", pk=pk)
    else:
        form = ClientForm(instance=client)
    return render(request, "core/client_form.html", {"form": form, "title": f"Edit: {client.name}"})


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
@login_required
def entity_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to create entities.")
        return redirect("core:client_detail", pk=client_pk)

    if request.method == "POST":
        form = EntityForm(request.POST)
        if form.is_valid():
            entity = form.save(commit=False)
            entity.client = client
            entity.save()
            _log_action(request, "import", f"Created entity: {entity.entity_name}", entity)
            messages.success(request, f"Entity '{entity.entity_name}' created.")
            return redirect("core:client_detail", pk=client_pk)
    else:
        form = EntityForm()
    return render(request, "core/entity_form.html", {
        "form": form, "client": client, "title": "Create Entity"
    })


@login_required
def entity_detail(request, pk):
    entity = get_object_or_404(Entity, pk=pk)
    financial_years = entity.financial_years.all()
    officers = entity.officers.filter(date_ceased__isnull=True)
    context = {"entity": entity, "financial_years": financial_years, "officers": officers}
    return render(request, "core/entity_detail.html", context)


@login_required
def entity_edit(request, pk):
    entity = get_object_or_404(Entity, pk=pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to edit entities.")
        return redirect("core:entity_detail", pk=pk)

    if request.method == "POST":
        form = EntityForm(request.POST, instance=entity)
        if form.is_valid():
            form.save()
            messages.success(request, f"Entity '{entity.entity_name}' updated.")
            return redirect("core:entity_detail", pk=pk)
    else:
        form = EntityForm(instance=entity)
    return render(request, "core/entity_form.html", {
        "form": form, "client": entity.client, "title": f"Edit: {entity.entity_name}"
    })


# ---------------------------------------------------------------------------
# Financial Years
# ---------------------------------------------------------------------------
@login_required
def financial_year_create(request, entity_pk):
    entity = get_object_or_404(Entity, pk=entity_pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission.")
        return redirect("core:entity_detail", pk=entity_pk)

    if request.method == "POST":
        form = FinancialYearForm(request.POST)
        if form.is_valid():
            fy = form.save(commit=False)
            fy.entity = entity
            # Link to prior year if exists
            prior = entity.financial_years.order_by("-end_date").first()
            if prior:
                fy.prior_year = prior
            fy.save()
            _log_action(request, "import", f"Created financial year: {fy.year_label}", fy)
            messages.success(request, f"Financial year '{fy.year_label}' created.")
            return redirect("core:financial_year_detail", pk=fy.pk)
    else:
        form = FinancialYearForm()
    return render(request, "core/financial_year_form.html", {
        "form": form, "entity": entity, "title": "Create Financial Year"
    })


@login_required
def financial_year_detail(request, pk):
    fy = get_object_or_404(
        FinancialYear.objects.select_related("entity", "entity__client", "prior_year"),
        pk=pk,
    )
    tb_lines = fy.trial_balance_lines.select_related("mapped_line_item").all()
    adjustments = fy.adjusting_journals.all()
    unmapped_count = tb_lines.filter(mapped_line_item__isnull=True).count()
    documents = fy.generated_documents.all()

    # Calculate totals
    total_debit = tb_lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")
    total_credit = tb_lines.aggregate(total=Sum("credit"))["total"] or Decimal("0")
    total_prior_debit = tb_lines.aggregate(total=Sum("prior_debit"))["total"] or Decimal("0")
    total_prior_credit = tb_lines.aggregate(total=Sum("prior_credit"))["total"] or Decimal("0")

    # Group lines by section for comparative display
    from collections import OrderedDict
    SECTION_ORDER = [
        'Revenue', 'Income', 'Cost of Sales', 'Expenses',
        'Current Assets', 'Non-Current Assets',
        'Current Liabilities', 'Non-Current Liabilities',
        'Equity', 'Income Tax',
    ]
    SECTION_DISPLAY = {
        'Revenue': 'Income', 'Income': 'Income',
        'Cost of Sales': 'Cost of Sales', 'Expenses': 'Expenses',
        'Current Assets': 'Current Assets', 'Non-Current Assets': 'Non Current Assets',
        'Current Liabilities': 'Current Liabilities', 'Non-Current Liabilities': 'Non Current Liabilities',
        'Equity': 'Equity', 'Income Tax': 'Equity',
    }
    sections = OrderedDict()
    for line in tb_lines:
        if line.mapped_line_item:
            raw_section = line.mapped_line_item.statement_section
            display_section = SECTION_DISPLAY.get(raw_section, raw_section)
        else:
            display_section = 'Unmapped'
        if display_section not in sections:
            sections[display_section] = []
        sections[display_section].append(line)
    ordered_sections = OrderedDict()
    section_keys_ordered = []
    for s in SECTION_ORDER:
        ds = SECTION_DISPLAY.get(s, s)
        if ds not in section_keys_ordered:
            section_keys_ordered.append(ds)
    for key in section_keys_ordered:
        if key in sections:
            ordered_sections[key] = sections[key]
    for key in sections:
        if key not in ordered_sections:
            ordered_sections[key] = sections[key]

    # Year labels
    current_year = str(fy.year_label)
    prior_year = str(int(fy.year_label) - 1) if fy.year_label.isdigit() else 'Prior'

    context = {
        "fy": fy,
        "entity": fy.entity,
        "client": fy.entity.client,
        "tb_lines": tb_lines,
        "tb_sections": ordered_sections,
        "adjustments": adjustments,
        "unmapped_count": unmapped_count,
        "documents": documents,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "total_prior_debit": total_prior_debit,
        "total_prior_credit": total_prior_credit,
        "current_year": current_year,
        "prior_year": prior_year,
    }
    return render(request, "core/financial_year_detail.html", context)


@login_required
def financial_year_status(request, pk):
    """Change the status of a financial year."""
    fy = get_object_or_404(FinancialYear, pk=pk)
    new_status = request.POST.get("status")

    if not new_status or new_status not in dict(FinancialYear.Status.choices):
        messages.error(request, "Invalid status.")
        return redirect("core:financial_year_detail", pk=pk)

    # Permission checks
    if new_status == "finalised" and not request.user.can_finalise:
        messages.error(request, "Only senior accountants can finalise.")
        return redirect("core:financial_year_detail", pk=pk)

    if new_status == "reviewed" and not request.user.is_senior:
        messages.error(request, "Only senior accountants can mark as reviewed.")
        return redirect("core:financial_year_detail", pk=pk)

    old_status = fy.status
    fy.status = new_status
    if new_status == "reviewed":
        fy.reviewed_by = request.user
    if new_status == "finalised":
        fy.finalised_at = timezone.now()
    fy.save()

    _log_action(
        request, "status_change",
        f"Changed {fy} from {old_status} to {new_status}", fy
    )
    messages.success(request, f"Status changed to {fy.get_status_display()}.")
    return redirect("core:financial_year_detail", pk=pk)


@login_required
def roll_forward(request, pk):
    """Create a new financial year from the current one, carrying closing balances."""
    current_fy = get_object_or_404(FinancialYear, pk=pk)
    entity = current_fy.entity

    if not request.user.can_edit:
        messages.error(request, "You do not have permission.")
        return redirect("core:financial_year_detail", pk=pk)

    if request.method == "POST":
        # Calculate new dates (add 1 year)
        from dateutil.relativedelta import relativedelta
        new_start = current_fy.end_date + relativedelta(days=1)
        new_end = current_fy.end_date + relativedelta(years=1)
        new_label = f"FY{new_end.year}"

        # Check if already exists
        if entity.financial_years.filter(year_label=new_label).exists():
            messages.warning(request, f"{new_label} already exists for this entity.")
            return redirect("core:financial_year_detail", pk=pk)

        # Create new FY
        new_fy = FinancialYear.objects.create(
            entity=entity,
            year_label=new_label,
            start_date=new_start,
            end_date=new_end,
            prior_year=current_fy,
            status=FinancialYear.Status.DRAFT,
        )

        # Carry forward closing balances as opening balances
        for line in current_fy.trial_balance_lines.filter(is_adjustment=False):
            TrialBalanceLine.objects.create(
                financial_year=new_fy,
                account_code=line.account_code,
                account_name=line.account_name,
                opening_balance=line.closing_balance,
                debit=Decimal("0"),
                credit=Decimal("0"),
                closing_balance=line.closing_balance,
                mapped_line_item=line.mapped_line_item,
                is_adjustment=False,
            )

        _log_action(request, "import", f"Rolled forward to {new_label}", new_fy)
        messages.success(request, f"Rolled forward to {new_label}. Opening balances carried from {current_fy.year_label}.")
        return redirect("core:financial_year_detail", pk=new_fy.pk)

    return render(request, "core/roll_forward_confirm.html", {"fy": current_fy})


# ---------------------------------------------------------------------------
# Trial Balance Import
# ---------------------------------------------------------------------------
@login_required
def trial_balance_import(request, pk):
    fy = get_object_or_404(FinancialYear, pk=pk)

    if fy.is_locked:
        messages.error(request, "Cannot import into a finalised financial year.")
        return redirect("core:financial_year_detail", pk=pk)

    if not request.user.can_edit:
        messages.error(request, "You do not have permission.")
        return redirect("core:financial_year_detail", pk=pk)

    if request.method == "POST":
        form = TrialBalanceUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES["file"]
            try:
                result = _process_trial_balance_upload(fy, file)
                _log_action(request, "import", f"Imported trial balance: {result['imported']} lines", fy)
                messages.success(
                    request,
                    f"Imported {result['imported']} lines. "
                    f"{result['unmapped']} unmapped accounts need attention."
                )
                if result["errors"]:
                    for err in result["errors"][:5]:
                        messages.warning(request, err)
                return redirect("core:financial_year_detail", pk=pk)
            except Exception as e:
                messages.error(request, f"Import failed: {str(e)}")
    else:
        form = TrialBalanceUploadForm()

    return render(request, "core/trial_balance_import.html", {
        "form": form, "fy": fy
    })


def _process_trial_balance_upload(fy, file):
    """Process an Excel trial balance upload."""
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    ws = wb.active

    # Clear existing non-adjustment lines
    fy.trial_balance_lines.filter(is_adjustment=False).delete()

    imported = 0
    unmapped = 0
    errors = []
    entity = fy.entity

    rows = list(ws.iter_rows(min_row=2, values_only=True))  # Skip header

    for i, row in enumerate(rows, start=2):
        if not row or not row[0]:
            continue

        try:
            account_code = str(row[0]).strip()
            account_name = str(row[1]).strip() if row[1] else ""
            opening_balance = Decimal(str(row[2] or 0))
            debit = Decimal(str(row[3] or 0))
            credit = Decimal(str(row[4] or 0))
            closing_balance = opening_balance + debit - credit
        except (InvalidOperation, ValueError, IndexError) as e:
            errors.append(f"Row {i}: {str(e)}")
            continue

        # Try to find existing mapping for this entity (learning from prior imports)
        mapping = ClientAccountMapping.objects.filter(
            entity=entity, client_account_code=account_code
        ).first()

        mapped_item = mapping.mapped_line_item if mapping else None

        # If no existing mapping, try to match against the standard chart of accounts
        # for this entity type. This provides automatic mapping for known account codes.
        coa_match = None
        if not mapped_item:
            coa_match = ChartOfAccount.objects.filter(
                entity_type=entity.entity_type,
                account_code=account_code,
                is_active=True,
            ).first()
            if coa_match and coa_match.maps_to:
                mapped_item = coa_match.maps_to

        TrialBalanceLine.objects.create(
            financial_year=fy,
            account_code=account_code,
            account_name=account_name,
            opening_balance=opening_balance,
            debit=debit,
            credit=credit,
            closing_balance=closing_balance,
            mapped_line_item=mapped_item,
            is_adjustment=False,
        )

        # Create or update client account mapping record
        ClientAccountMapping.objects.update_or_create(
            entity=entity,
            client_account_code=account_code,
            defaults={"client_account_name": account_name, "mapped_line_item": mapped_item},
        )

        imported += 1
        if not mapped_item:
            unmapped += 1

    wb.close()
    return {"imported": imported, "unmapped": unmapped, "errors": errors}


@login_required
def trial_balance_view(request, pk):
    fy = get_object_or_404(FinancialYear, pk=pk)
    tb_lines = fy.trial_balance_lines.select_related("mapped_line_item").all()
    return render(request, "core/trial_balance_view.html", {"fy": fy, "tb_lines": tb_lines})


# ---------------------------------------------------------------------------
# Account Mapping
# ---------------------------------------------------------------------------
@login_required
def account_mapping_list(request):
    mappings = AccountMapping.objects.all()
    return render(request, "core/account_mapping_list.html", {"mappings": mappings})


@login_required
def account_mapping_create(request):
    if not request.user.is_admin:
        messages.error(request, "Only administrators can manage standard mappings.")
        return redirect("core:account_mapping_list")

    if request.method == "POST":
        form = AccountMappingForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account mapping created.")
            return redirect("core:account_mapping_list")
    else:
        form = AccountMappingForm()
    return render(request, "core/account_mapping_form.html", {"form": form, "title": "Create Standard Mapping"})


@login_required
def map_client_accounts(request, pk):
    """Map unmapped client accounts to standard line items for a financial year."""
    fy = get_object_or_404(FinancialYear, pk=pk)
    entity = fy.entity

    unmapped = ClientAccountMapping.objects.filter(
        entity=entity, mapped_line_item__isnull=True
    )
    standard_mappings = AccountMapping.objects.all()

    if request.method == "POST":
        mapped_count = 0
        for cam in unmapped:
            mapping_id = request.POST.get(f"mapping_{cam.pk}")
            if mapping_id:
                try:
                    cam.mapped_line_item = AccountMapping.objects.get(pk=mapping_id)
                    cam.save()
                    # Update trial balance lines with this mapping
                    TrialBalanceLine.objects.filter(
                        financial_year=fy,
                        account_code=cam.client_account_code,
                    ).update(mapped_line_item=cam.mapped_line_item)
                    mapped_count += 1
                except AccountMapping.DoesNotExist:
                    pass

        _log_action(request, "mapping_change", f"Mapped {mapped_count} accounts", fy)
        messages.success(request, f"Mapped {mapped_count} accounts.")
        return redirect("core:financial_year_detail", pk=pk)

    context = {
        "fy": fy,
        "unmapped": unmapped,
        "standard_mappings": standard_mappings,
    }
    return render(request, "core/map_client_accounts.html", context)


# ---------------------------------------------------------------------------
# Journal Entries (Enhanced)
# ---------------------------------------------------------------------------
@login_required
def adjustment_list(request, pk):
    fy = get_object_or_404(FinancialYear, pk=pk)
    adjustments = fy.adjusting_journals.prefetch_related("lines").all()
    return render(request, "core/adjustment_list.html", {"fy": fy, "adjustments": adjustments})


@login_required
def adjustment_create(request, pk):
    fy = get_object_or_404(FinancialYear, pk=pk)

    if fy.is_locked:
        messages.error(request, "Cannot add journals to a finalised year.")
        return redirect("core:financial_year_detail", pk=pk)

    if not request.user.can_edit:
        messages.error(request, "You do not have permission.")
        return redirect("core:financial_year_detail", pk=pk)

    # Get available accounts for the account picker
    accounts = list(
        ClientAccountMapping.objects.filter(entity=fy.entity)
        .order_by("client_account_code")
        .values("client_account_code", "client_account_name")
    )

    if request.method == "POST":
        form = AdjustingJournalForm(request.POST)
        formset = JournalLineFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            journal = form.save(commit=False)
            journal.financial_year = fy
            journal.created_by = request.user
            journal.save()  # This auto-generates reference_number

            formset.instance = journal
            lines = formset.save()

            # Validate debits = credits
            total_dr = sum(l.debit for l in lines)
            total_cr = sum(l.credit for l in lines)
            if total_dr != total_cr:
                journal.delete()
                messages.error(request, f"Journal does not balance: Dr ${total_dr:,.2f} \u2260 Cr ${total_cr:,.2f}")
                return render(request, "core/adjustment_form.html", {
                    "form": form, "formset": formset, "fy": fy, "accounts": accounts
                })

            # Update cached totals
            journal.total_debit = total_dr
            journal.total_credit = total_cr
            journal.save(update_fields=["total_debit", "total_credit"])

            _log_action(request, "adjustment", f"Created journal {journal.reference_number}: {journal.description}", journal)
            messages.success(request, f"Journal {journal.reference_number} created as Draft.")
            return redirect("core:financial_year_detail", pk=pk)
    else:
        form = AdjustingJournalForm(initial={"journal_date": fy.end_date})
        formset = JournalLineFormSet()

    return render(request, "core/adjustment_form.html", {
        "form": form, "formset": formset, "fy": fy, "accounts": accounts
    })


@login_required
def journal_detail(request, pk):
    """View a single journal entry with all its lines and audit info."""
    journal = get_object_or_404(
        AdjustingJournal.objects.select_related(
            "financial_year", "financial_year__entity",
            "created_by", "posted_by"
        ).prefetch_related("lines"),
        pk=pk,
    )
    fy = journal.financial_year
    entity = fy.entity
    client = entity.client
    return render(request, "core/journal_detail.html", {
        "journal": journal, "fy": fy, "entity": entity, "client": client,
    })


@login_required
def journal_post(request, pk):
    """Post a draft journal — creates adjustment TB lines."""
    journal = get_object_or_404(AdjustingJournal, pk=pk)
    fy = journal.financial_year

    if journal.status != AdjustingJournal.JournalStatus.DRAFT:
        messages.error(request, "Only draft journals can be posted.")
        return redirect("core:journal_detail", pk=pk)

    if not journal.is_balanced:
        messages.error(request, "Journal does not balance. Cannot post.")
        return redirect("core:journal_detail", pk=pk)

    if fy.is_locked:
        messages.error(request, "Cannot post to a finalised year.")
        return redirect("core:journal_detail", pk=pk)

    # Create adjustment trial balance lines
    for line in journal.lines.all():
        mapping = ClientAccountMapping.objects.filter(
            entity=fy.entity, client_account_code=line.account_code
        ).first()
        mapped_item = mapping.mapped_line_item if mapping else None

        TrialBalanceLine.objects.create(
            financial_year=fy,
            account_code=line.account_code,
            account_name=line.account_name,
            opening_balance=Decimal("0"),
            debit=line.debit,
            credit=line.credit,
            closing_balance=line.debit - line.credit,
            mapped_line_item=mapped_item,
            is_adjustment=True,
        )

    # Update journal status
    journal.status = AdjustingJournal.JournalStatus.POSTED
    journal.posted_by = request.user
    journal.posted_at = timezone.now()
    journal.save(update_fields=["status", "posted_by", "posted_at"])

    _log_action(request, "adjustment", f"Posted journal {journal.reference_number}", journal)
    messages.success(request, f"Journal {journal.reference_number} has been posted.")
    return redirect("core:financial_year_detail", pk=fy.pk)


@login_required
def journal_delete(request, pk):
    """Delete a journal entry. If posted, also removes its adjustment TB lines."""
    journal = get_object_or_404(AdjustingJournal, pk=pk)
    fy = journal.financial_year

    if fy.is_locked:
        messages.error(request, "Cannot delete journals in a finalised year.")
        return redirect("core:journal_detail", pk=pk)

    if not request.user.can_edit:
        messages.error(request, "You do not have permission to delete journals.")
        return redirect("core:journal_detail", pk=pk)

    ref = journal.reference_number
    status = journal.status

    # If the journal was posted, remove its adjustment TB lines
    if status == AdjustingJournal.JournalStatus.POSTED:
        for line in journal.lines.all():
            TrialBalanceLine.objects.filter(
                financial_year=fy,
                account_code=line.account_code,
                debit=line.debit,
                credit=line.credit,
                is_adjustment=True,
            ).first().delete() if TrialBalanceLine.objects.filter(
                financial_year=fy,
                account_code=line.account_code,
                debit=line.debit,
                credit=line.credit,
                is_adjustment=True,
            ).exists() else None

    journal.delete()
    _log_action(request, "adjustment", f"Deleted {status} journal {ref}")
    messages.success(request, f"Journal {ref} has been deleted.")
    return redirect("core:financial_year_detail", pk=fy.pk)


@login_required
def account_list_api(request, pk):
    """JSON API endpoint returning available accounts for a financial year's entity."""
    fy = get_object_or_404(FinancialYear, pk=pk)
    accounts = list(
        ClientAccountMapping.objects.filter(entity=fy.entity)
        .order_by("client_account_code")
        .values("client_account_code", "client_account_name")
    )
    # Also include accounts from the trial balance that may not be mapped
    tb_accounts = list(
        fy.trial_balance_lines.filter(is_adjustment=False)
        .values("account_code", "account_name")
        .distinct()
        .order_by("account_code")
    )
    # Merge: use TB accounts as base, supplement with mapped accounts
    account_dict = {}
    for a in tb_accounts:
        account_dict[a["account_code"]] = a["account_name"]
    for a in accounts:
        if a["client_account_code"] not in account_dict:
            account_dict[a["client_account_code"]] = a["client_account_name"]

    result = [
        {"code": code, "name": name}
        for code, name in sorted(account_dict.items())
    ]
    return JsonResponse(result, safe=False)


# ---------------------------------------------------------------------------
# Financial Statements Preview
# ---------------------------------------------------------------------------
@login_required
def financial_statements_view(request, pk):
    """Render a preview of the financial statements on screen."""
    fy = get_object_or_404(
        FinancialYear.objects.select_related("entity", "prior_year"),
        pk=pk,
    )

    # Aggregate trial balance by mapped line item
    from django.db.models import Sum as DSum
    current_data = (
        fy.trial_balance_lines
        .filter(mapped_line_item__isnull=False)
        .values(
            "mapped_line_item__standard_code",
            "mapped_line_item__line_item_label",
            "mapped_line_item__financial_statement",
            "mapped_line_item__statement_section",
            "mapped_line_item__display_order",
        )
        .annotate(total=DSum("closing_balance"))
        .order_by("mapped_line_item__display_order")
    )

    # Get prior year data if available
    prior_data = {}
    if fy.prior_year:
        prior_lines = (
            fy.prior_year.trial_balance_lines
            .filter(mapped_line_item__isnull=False)
            .values("mapped_line_item__standard_code")
            .annotate(total=DSum("closing_balance"))
        )
        prior_data = {item["mapped_line_item__standard_code"]: item["total"] for item in prior_lines}

    # Organise into statements
    income_statement = []
    balance_sheet = []
    for item in current_data:
        entry = {
            "code": item["mapped_line_item__standard_code"],
            "label": item["mapped_line_item__line_item_label"],
            "section": item["mapped_line_item__statement_section"],
            "current": item["total"],
            "prior": prior_data.get(item["mapped_line_item__standard_code"], Decimal("0")),
        }
        if item["mapped_line_item__financial_statement"] == "income_statement":
            income_statement.append(entry)
        elif item["mapped_line_item__financial_statement"] == "balance_sheet":
            balance_sheet.append(entry)

    context = {
        "fy": fy,
        "entity": fy.entity,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
    }
    return render(request, "core/financial_statements_view.html", context)


# ---------------------------------------------------------------------------
# Document Generation (placeholder for Phase 2)
# ---------------------------------------------------------------------------
@login_required
def generate_document(request, pk):
    fy = get_object_or_404(FinancialYear, pk=pk)

    # Check that there are trial balance lines
    if not fy.trial_balance_lines.exists():
        messages.error(request, "Cannot generate statements: no trial balance data loaded.")
        return redirect("core:financial_year_detail", pk=pk)

    # Determine requested format (default: docx)
    fmt = request.GET.get("format", "docx").lower()
    if fmt not in ("docx", "pdf"):
        fmt = "docx"

    from .docgen import generate_financial_statements

    try:
        buffer = generate_financial_statements(fy.pk)
    except Exception as e:
        messages.error(request, f"Document generation failed: {e}")
        return redirect("core:financial_year_detail", pk=pk)

    # Build filename
    entity_name = fy.entity.entity_name.replace(" ", "_")
    base_filename = f"{entity_name}_Financial_Statements_{fy.year_label}"

    if fmt == "pdf":
        # Convert DOCX buffer to PDF via LibreOffice
        import subprocess, tempfile, os
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                docx_path = os.path.join(tmpdir, f"{base_filename}.docx")
                with open(docx_path, "wb") as f:
                    f.write(buffer.getvalue())
                result = subprocess.run(
                    ["libreoffice", "--headless", "--convert-to", "pdf",
                     "--outdir", tmpdir, docx_path],
                    capture_output=True, timeout=60,
                )
                pdf_path = os.path.join(tmpdir, f"{base_filename}.pdf")
                if not os.path.exists(pdf_path):
                    raise RuntimeError(
                        f"PDF conversion failed: {result.stderr.decode('utf-8', errors='replace')}"
                    )
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

            filename = f"{base_filename}.pdf"
            response = HttpResponse(
                pdf_bytes,
                content_type="application/pdf",
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            file_content = pdf_bytes
            file_format = "pdf"
        except Exception as e:
            messages.error(request, f"PDF conversion failed: {e}. Falling back to DOCX.")
            filename = f"{base_filename}.docx"
            response = HttpResponse(
                buffer.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            file_content = buffer.getvalue()
            file_format = "docx"
    else:
        filename = f"{base_filename}.docx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        file_content = buffer.getvalue()
        file_format = "docx"

    # Log the generation
    _log_action(request, "generate", f"Generated financial statements ({file_format.upper()}) for {fy}", fy)

    # Save record
    from django.core.files.base import ContentFile
    doc = GeneratedDocument(
        financial_year=fy,
        file_format=file_format,
        generated_by=request.user,
    )
    doc.file.save(filename, ContentFile(file_content), save=True)

    return response


# ---------------------------------------------------------------------------
# HTMX Partials
# ---------------------------------------------------------------------------
@login_required
def htmx_client_search(request):
    query = request.GET.get("q", "")
    if len(query) < 2:
        return HttpResponse("")

    if request.user.is_admin:
        clients = Client.objects.filter(is_active=True)
    else:
        clients = Client.objects.filter(
            assigned_accountant=request.user, is_active=True
        )

    clients = clients.filter(
        Q(name__icontains=query)
        | Q(entities__abn__icontains=query)
        | Q(entities__entity_name__icontains=query)
    ).distinct()[:20]

    return render(request, "partials/client_list_rows.html", {"clients": clients})


@login_required
def htmx_map_tb_line(request, pk):
    """HTMX endpoint to map a single trial balance line."""
    line = get_object_or_404(TrialBalanceLine, pk=pk)
    mapping_id = request.POST.get("mapped_line_item")

    if mapping_id:
        try:
            mapping = AccountMapping.objects.get(pk=mapping_id)
            line.mapped_line_item = mapping
            line.save()

            # Also save to client account mapping for reuse
            ClientAccountMapping.objects.update_or_create(
                entity=line.financial_year.entity,
                client_account_code=line.account_code,
                defaults={
                    "client_account_name": line.account_name,
                    "mapped_line_item": mapping,
                },
            )
        except AccountMapping.DoesNotExist:
            pass

    mappings = AccountMapping.objects.all()
    return render(request, "partials/tb_line_row.html", {
        "line": line, "mappings": mappings
    })


# ---------------------------------------------------------------------------
# Entity Officers / Signatories
# ---------------------------------------------------------------------------
@login_required
def entity_officers(request, pk):
    """List all officers/signatories for an entity."""
    entity = get_object_or_404(Entity, pk=pk)
    officers = entity.officers.all()

    officer_label_map = {
        "company": "Director / Officer",
        "trust": "Trustee / Beneficiary",
        "partnership": "Partner",
        "sole_trader": "Proprietor",
        "smsf": "Trustee / Director",
    }
    officer_label = officer_label_map.get(entity.entity_type, "Officer")

    return render(request, "core/entity_officers.html", {
        "entity": entity,
        "officers": officers,
        "officer_label": officer_label,
    })


@login_required
def entity_officer_create(request, entity_pk):
    """Add a new officer/signatory to an entity."""
    entity = get_object_or_404(Entity, pk=entity_pk)

    if request.method == "POST":
        form = EntityOfficerForm(request.POST, entity_type=entity.entity_type)
        if form.is_valid():
            officer = form.save(commit=False)
            officer.entity = entity
            officer.save()
            _log_action(request, "user_change",
                        f"Added officer {officer.full_name} to {entity.entity_name}",
                        officer)
            messages.success(request, f"Added {officer.full_name} as {officer.get_role_display()}.")
            return redirect("core:entity_officers", pk=entity.pk)
    else:
        form = EntityOfficerForm(entity_type=entity.entity_type)

    return render(request, "core/entity_officer_form.html", {
        "form": form,
        "entity": entity,
    })


@login_required
def entity_officer_edit(request, pk):
    """Edit an existing officer/signatory."""
    officer = get_object_or_404(EntityOfficer, pk=pk)
    entity = officer.entity

    if request.method == "POST":
        form = EntityOfficerForm(request.POST, instance=officer, entity_type=entity.entity_type)
        if form.is_valid():
            form.save()
            _log_action(request, "user_change",
                        f"Updated officer {officer.full_name} for {entity.entity_name}",
                        officer)
            messages.success(request, f"Updated {officer.full_name}.")
            return redirect("core:entity_officers", pk=entity.pk)
    else:
        form = EntityOfficerForm(instance=officer, entity_type=entity.entity_type)

    return render(request, "core/entity_officer_form.html", {
        "form": form,
        "entity": entity,
    })


@login_required
def entity_officer_delete(request, pk):
    """Delete an officer/signatory."""
    officer = get_object_or_404(EntityOfficer, pk=pk)
    entity = officer.entity
    name = officer.full_name
    _log_action(request, "user_change",
                f"Removed officer {name} from {entity.entity_name}",
                officer)
    officer.delete()
    messages.success(request, f"Removed {name}.")
    return redirect("core:entity_officers", pk=entity.pk)


# ---------------------------------------------------------------------------
# Access Ledger Import
# ---------------------------------------------------------------------------
@login_required
def access_ledger_import(request):
    """Import an Access Ledger ZIP export."""
    from .access_ledger_import import import_access_ledger_zip

    result = None

    if request.method == "POST":
        zip_file = request.FILES.get("zip_file")
        if not zip_file:
            messages.error(request, "Please select a ZIP file.")
        elif not zip_file.name.lower().endswith(".zip"):
            messages.error(request, "File must be a .zip file.")
        else:
            replace = request.POST.get("replace_existing") == "1"
            try:
                result = import_access_ledger_zip(
                    zip_file,
                    replace_existing=replace,
                )
                if result["errors"]:
                    messages.warning(
                        request,
                        f"Import completed with {len(result['errors'])} error(s)."
                    )
                else:
                    messages.success(
                        request,
                        f"Successfully imported {result['entity'].entity_name}: "
                        f"{result['years_imported']} years, "
                        f"{result['total_tb_lines']} TB lines, "
                        f"{result['total_dep_assets']} depreciation assets."
                    )
                _log_action(
                    request, "import",
                    f"Imported Access Ledger ZIP: {zip_file.name} "
                    f"({result['years_imported']} years)",
                    result.get("entity"),
                )
            except Exception as e:
                messages.error(request, f"Import failed: {str(e)}")

    return render(request, "core/access_ledger_import.html", {
        "result": result,
    })


# ============================================================
# PDF Downloads: Trial Balance & Journals List
# ============================================================

@login_required
def trial_balance_pdf(request, pk):
    """Generate a comparative trial balance PDF matching professional accounting format."""
    from io import BytesIO
    from collections import OrderedDict
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Table, TableStyle,
        Paragraph, Spacer, Image, NextPageTemplate, PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    import os
    from django.conf import settings

    fy = get_object_or_404(FinancialYear, pk=pk)
    entity = fy.entity
    tb_lines = TrialBalanceLine.objects.filter(financial_year=fy).select_related('mapped_line_item').order_by('account_code')

    # Determine section ordering and grouping
    SECTION_ORDER = [
        'Revenue', 'Income', 'Cost of Sales', 'Expenses',
        'Current Assets', 'Non-Current Assets',
        'Current Liabilities', 'Non-Current Liabilities',
        'Equity', 'Income Tax',
    ]
    SECTION_DISPLAY = {
        'Revenue': 'Income', 'Income': 'Income',
        'Cost of Sales': 'Cost of Sales', 'Expenses': 'Expenses',
        'Current Assets': 'Current Assets', 'Non-Current Assets': 'Non Current Assets',
        'Current Liabilities': 'Current Liabilities', 'Non-Current Liabilities': 'Non Current Liabilities',
        'Equity': 'Equity', 'Income Tax': 'Equity',
    }

    # Group lines by section
    sections = OrderedDict()
    unmapped_lines = []
    for line in tb_lines:
        if line.mapped_line_item:
            raw_section = line.mapped_line_item.statement_section
            display_section = SECTION_DISPLAY.get(raw_section, raw_section)
        else:
            display_section = 'Unmapped'
        if display_section not in sections:
            sections[display_section] = []
        sections[display_section].append(line)

    # Sort sections by defined order
    ordered_sections = OrderedDict()
    section_keys_ordered = []
    for s in SECTION_ORDER:
        ds = SECTION_DISPLAY.get(s, s)
        if ds not in section_keys_ordered:
            section_keys_ordered.append(ds)
    for key in section_keys_ordered:
        if key in sections:
            ordered_sections[key] = sections[key]
    # Add any remaining sections
    for key in sections:
        if key not in ordered_sections:
            ordered_sections[key] = sections[key]

    # Year labels
    current_year = str(fy.year_label)
    prior_year = str(int(fy.year_label) - 1) if fy.year_label.isdigit() else 'Prior'

    # ABN
    abn = entity.abn if hasattr(entity, 'abn') and entity.abn else ''
    abn_display = ''
    if abn:
        abn_clean = abn.replace(' ', '')
        if len(abn_clean) == 11:
            abn_display = f'ABN {abn_clean[:2]} {abn_clean[2:5]} {abn_clean[5:8]} {abn_clean[8:11]}'
        else:
            abn_display = f'ABN {abn}'

    buffer = BytesIO()

    # Custom page template with header and footer on every page
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'mcs_logo.png')

    class TBDocTemplate(BaseDocTemplate):
        def __init__(self, *args, **kwargs):
            self.entity_name = kwargs.pop('entity_name', '')
            self.abn_display = kwargs.pop('abn_display', '')
            self.end_date_str = kwargs.pop('end_date_str', '')
            self.current_year = kwargs.pop('current_year', '')
            self.prior_year = kwargs.pop('prior_year', '')
            super().__init__(*args, **kwargs)

        def afterPage(self):
            """Draw footer on every page."""
            canvas = self.canv
            canvas.saveState()
            # Footer line
            canvas.setStrokeColor(colors.HexColor('#333333'))
            canvas.setLineWidth(0.5)
            canvas.line(15*mm, 18*mm, A4[0] - 15*mm, 18*mm)
            # Footer text
            canvas.setFont('Helvetica-Bold', 7)
            canvas.setFillColor(colors.HexColor('#333333'))
            footer_text = (
                "These financial statements are unaudited. They must be read in conjunction with the attached "
                "Accountant's Compilation Report and Notes which form part of these financial statements."
            )
            # Center the text
            text_width = canvas.stringWidth(footer_text, 'Helvetica-Bold', 7)
            page_width = A4[0]
            if text_width > page_width - 30*mm:
                # Two-line footer
                line1 = "These financial statements are unaudited. They must be read in conjunction with the attached Accountant's"
                line2 = "Compilation Report and Notes which form part of these financial statements."
                w1 = canvas.stringWidth(line1, 'Helvetica-Bold', 7)
                w2 = canvas.stringWidth(line2, 'Helvetica-Bold', 7)
                canvas.drawString((page_width - w1) / 2, 13*mm, line1)
                canvas.drawString((page_width - w2) / 2, 10*mm, line2)
            else:
                canvas.drawString((page_width - text_width) / 2, 12*mm, footer_text)
            canvas.restoreState()

    doc = TBDocTemplate(
        buffer, pagesize=A4, topMargin=15*mm, bottomMargin=25*mm,
        leftMargin=15*mm, rightMargin=15*mm,
        entity_name=entity.entity_name.upper(),
        abn_display=abn_display,
        end_date_str=fy.end_date.strftime('%d %B %Y'),
        current_year=current_year,
        prior_year=prior_year,
    )

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id='main'
    )
    doc.addPageTemplates([PageTemplate(id='main', frames=[frame])])

    styles = getSampleStyleSheet()
    elements = []

    # Styles
    s_entity = ParagraphStyle('Entity', fontName='Helvetica-Bold', fontSize=14,
                               alignment=TA_CENTER, spaceAfter=2*mm)
    s_abn = ParagraphStyle('ABN', fontName='Helvetica', fontSize=10,
                            alignment=TA_CENTER, spaceAfter=2*mm)
    s_title = ParagraphStyle('TBTitle', fontName='Helvetica-Bold', fontSize=11,
                              alignment=TA_CENTER, spaceAfter=6*mm)
    s_section = ParagraphStyle('Section', fontName='Helvetica-Bold', fontSize=11,
                                spaceBefore=5*mm, spaceAfter=2*mm)
    s_cell = ParagraphStyle('Cell', fontName='Helvetica', fontSize=9)
    s_cell_bold = ParagraphStyle('CellBold', fontName='Helvetica-Bold', fontSize=9)
    s_num = ParagraphStyle('Num', fontName='Helvetica', fontSize=9, alignment=TA_RIGHT)
    s_num_bold = ParagraphStyle('NumBold', fontName='Helvetica-Bold', fontSize=9, alignment=TA_RIGHT)

    # Logo
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=25*mm, height=25*mm)
        logo.hAlign = 'CENTER'
        elements.append(logo)
        elements.append(Spacer(1, 2*mm))

    # Header
    elements.append(Paragraph(entity.entity_name.upper(), s_entity))
    if abn_display:
        elements.append(Paragraph(abn_display, s_abn))
    elements.append(Paragraph(
        f"Comparative Trial Balance as at {fy.end_date.strftime('%d %B %Y')}", s_title
    ))

    # Column header table
    col_widths = [50, 165, 75, 75, 75, 75]
    header_data = [
        ['', '', current_year, current_year, prior_year, prior_year],
        ['', '', '$ Dr', '$ Cr', '$ Dr', '$ Cr'],
    ]
    header_table = Table(header_data, colWidths=col_widths)
    header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('LINEBELOW', (2, 1), (-1, 1), 0.8, colors.HexColor('#333333')),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(header_table)

    def fmt(val):
        """Format a decimal value with commas, or return empty string if zero."""
        if val and val != Decimal('0'):
            return f"{val:,.2f}"
        return ''

    # Totals accumulators
    grand_total_dr = Decimal('0')
    grand_total_cr = Decimal('0')
    grand_total_prior_dr = Decimal('0')
    grand_total_prior_cr = Decimal('0')

    # Build section tables
    for section_name, lines in ordered_sections.items():
        elements.append(Paragraph(f"<b>{section_name}</b>", s_section))

        data = []
        for line in lines:
            dr = line.debit if line.debit else Decimal('0')
            cr = line.credit if line.credit else Decimal('0')
            prior_dr = line.prior_debit if line.prior_debit else Decimal('0')
            prior_cr = line.prior_credit if line.prior_credit else Decimal('0')

            grand_total_dr += dr
            grand_total_cr += cr
            grand_total_prior_dr += prior_dr
            grand_total_prior_cr += prior_cr

            row = [
                Paragraph(f"<b>{line.account_code}</b>", ParagraphStyle('Code', fontName='Helvetica-Bold', fontSize=9)),
                Paragraph(line.account_name, s_cell),
                fmt(dr),
                fmt(cr),
                fmt(prior_dr),
                fmt(prior_cr),
            ]
            data.append(row)

        if data:
            section_table = Table(data, colWidths=col_widths)
            style_cmds = [
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ]
            section_table.setStyle(TableStyle(style_cmds))
            elements.append(section_table)

    # Grand totals
    elements.append(Spacer(1, 3*mm))
    totals_data = [[
        '', '',
        f"{grand_total_dr:,.2f}",
        f"{grand_total_cr:,.2f}",
        f"{grand_total_prior_dr:,.2f}",
        f"{grand_total_prior_cr:,.2f}",
    ]]
    totals_table = Table(totals_data, colWidths=col_widths)
    totals_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE', (2, 0), (-1, 0), 1.0, colors.HexColor('#333333')),
        ('LINEBELOW', (2, 0), (-1, 0), 0.5, colors.HexColor('#333333')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(totals_table)

    # Net Profit
    net_profit_current = grand_total_cr - grand_total_dr
    net_profit_prior = grand_total_prior_cr - grand_total_prior_dr
    elements.append(Spacer(1, 3*mm))
    profit_data = [[
        '', Paragraph('<b>Net Profit</b>', s_cell_bold),
        '', f"{abs(net_profit_current):,.2f}",
        '', f"{abs(net_profit_prior):,.2f}",
    ]]
    profit_table = Table(profit_data, colWidths=col_widths)
    profit_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('LINEBELOW', (2, 0), (-1, 0), 0.8, colors.HexColor('#333333')),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(profit_table)

    doc.build(elements)
    buffer.seek(0)

    filename = f"Comparative_TB_{entity.entity_name.replace(' ', '_')}_{fy.year_label}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def journals_pdf(request, pk):
    """Generate a PDF listing all journal entries for a financial year."""
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import os

    fy = get_object_or_404(FinancialYear, pk=pk)
    entity = fy.entity
    journals = AdjustingJournal.objects.filter(financial_year=fy).prefetch_related('lines').order_by('created_at')

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    elements = []

    # Logo
    from django.conf import settings
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'mcs_logo.png')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=40*mm, height=40*mm)
        logo.hAlign = 'LEFT'
        elements.append(logo)
        elements.append(Spacer(1, 3*mm))

    # Title
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=16, spaceAfter=4*mm)
    elements.append(Paragraph(f"{entity.entity_name}", title_style))

    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=11, textColor=colors.grey, spaceAfter=2*mm)
    elements.append(Paragraph(f"Journal Entries — {fy.year_label}", subtitle_style))
    elements.append(Paragraph(
        f"{fy.start_date.strftime('%d %b %Y')} to {fy.end_date.strftime('%d %b %Y')} · Status: {fy.get_status_display()}",
        ParagraphStyle('DateLine', parent=styles['Normal'], fontSize=9, textColor=colors.grey, spaceAfter=6*mm)
    ))

    if not journals.exists():
        elements.append(Paragraph("No journal entries recorded for this financial year.", styles['Normal']))
    else:
        # Summary table
        summary_data = [
            ['Total Journals', str(journals.count())],
            ['Posted', str(journals.filter(status='posted').count())],
            ['Draft', str(journals.filter(status='draft').count())],
        ]
        summary_table = Table(summary_data, colWidths=[100, 80])
        summary_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 6*mm))

        # Each journal
        for journal in journals:
            journal_elements = []

            # Journal header
            ref = journal.reference_number or 'DRAFT'
            status_text = journal.get_status_display()
            jtype = journal.get_journal_type_display()
            header_text = (
                f"<b>{ref}</b> · {jtype} · {status_text} · "
                f"{journal.journal_date.strftime('%d %b %Y')}"
            )
            journal_elements.append(Paragraph(header_text, ParagraphStyle(
                'JournalHeader', fontSize=10, spaceAfter=1*mm,
                textColor=colors.HexColor('#212529')
            )))

            if journal.description:
                journal_elements.append(Paragraph(
                    journal.description,
                    ParagraphStyle('JDesc', fontSize=8, textColor=colors.grey, spaceAfter=2*mm)
                ))

            # Lines table
            lines = journal.lines.all()
            line_header = ['Account', 'Name', 'Description', 'Debit', 'Credit']
            line_data = [line_header]
            total_dr = Decimal('0')
            total_cr = Decimal('0')

            for line in lines:
                line_data.append([
                    line.account_code,
                    Paragraph(line.account_name, ParagraphStyle('LCell', fontSize=7)),
                    Paragraph(line.description or '', ParagraphStyle('LCell2', fontSize=7, textColor=colors.grey)),
                    f"{line.debit:,.2f}" if line.debit else '',
                    f"{line.credit:,.2f}" if line.credit else '',
                ])
                total_dr += line.debit or Decimal('0')
                total_cr += line.credit or Decimal('0')

            line_data.append(['', '', Paragraph('<b>Total</b>', ParagraphStyle('Bold', fontSize=7)),
                              f"{total_dr:,.2f}", f"{total_cr:,.2f}"])

            line_table = Table(line_data, colWidths=[50, 120, 130, 65, 65], repeatRows=1)
            line_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#495057')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8f9fa')]),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e9ecef')),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            journal_elements.append(line_table)

            # Created by info
            created_by = journal.created_by.get_full_name() if journal.created_by else 'System'
            journal_elements.append(Paragraph(
                f"Created by {created_by} on {journal.created_at.strftime('%d/%m/%Y %H:%M')}",
                ParagraphStyle('CreatedBy', fontSize=6, textColor=colors.grey, spaceBefore=1*mm)
            ))
            journal_elements.append(Spacer(1, 5*mm))

            elements.append(KeepTogether(journal_elements))

    # Footer
    elements.append(Spacer(1, 4*mm))
    footer_style = ParagraphStyle('Footer', fontSize=7, textColor=colors.grey)
    elements.append(Paragraph(
        f"Generated by StatementHub on {timezone.now().strftime('%d %b %Y at %H:%M')} · MC & S Pty Ltd",
        footer_style
    ))

    doc.build(elements)
    buffer.seek(0)

    filename = f"Journals_{entity.entity_name.replace(' ', '_')}_{fy.year_label}.pdf"
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Client Associates (Family & Business)
# ---------------------------------------------------------------------------
@login_required
def associate_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to add associates.")
        return redirect("core:client_detail", pk=client_pk)

    if request.method == "POST":
        form = ClientAssociateForm(request.POST)
        if form.is_valid():
            assoc = form.save(commit=False)
            assoc.client = client
            assoc.save()
            _log_action(request, "import", f"Added associate: {assoc.name} ({assoc.get_relationship_type_display()})", assoc)
            messages.success(request, f"Associate '{assoc.name}' added.")
            return redirect("core:client_detail", pk=client_pk)
    else:
        form = ClientAssociateForm()
    return render(request, "core/associate_form.html", {
        "form": form, "client": client, "title": "Add Associate"
    })


@login_required
def associate_edit(request, pk):
    assoc = get_object_or_404(ClientAssociate, pk=pk)
    client = assoc.client
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to edit associates.")
        return redirect("core:client_detail", pk=client.pk)

    if request.method == "POST":
        form = ClientAssociateForm(request.POST, instance=assoc)
        if form.is_valid():
            form.save()
            messages.success(request, f"Associate '{assoc.name}' updated.")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = ClientAssociateForm(instance=assoc)
    return render(request, "core/associate_form.html", {
        "form": form, "client": client, "title": f"Edit: {assoc.name}"
    })


@login_required
def associate_delete(request, pk):
    assoc = get_object_or_404(ClientAssociate, pk=pk)
    client = assoc.client
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to delete associates.")
        return redirect("core:client_detail", pk=client.pk)

    if request.method == "POST":
        name = assoc.name
        assoc.delete()
        messages.success(request, f"Associate '{name}' removed.")
    return redirect("core:client_detail", pk=client.pk)


# ---------------------------------------------------------------------------
# Accounting Software
# ---------------------------------------------------------------------------
@login_required
def software_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to add software configs.")
        return redirect("core:client_detail", pk=client_pk)

    if request.method == "POST":
        form = AccountingSoftwareForm(request.POST, client=client)
        if form.is_valid():
            sw = form.save(commit=False)
            sw.client = client
            sw.save()
            _log_action(request, "import", f"Added software: {sw.get_software_type_display()}", sw)
            messages.success(request, f"Software '{sw.get_software_type_display()}' added.")
            return redirect("core:client_detail", pk=client_pk)
    else:
        form = AccountingSoftwareForm(client=client)
    return render(request, "core/software_form.html", {
        "form": form, "client": client, "title": "Add Accounting Software"
    })


@login_required
def software_edit(request, pk):
    sw = get_object_or_404(AccountingSoftware, pk=pk)
    client = sw.client
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to edit software configs.")
        return redirect("core:client_detail", pk=client.pk)

    if request.method == "POST":
        form = AccountingSoftwareForm(request.POST, instance=sw, client=client)
        if form.is_valid():
            form.save()
            messages.success(request, f"Software '{sw.get_software_type_display()}' updated.")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = AccountingSoftwareForm(instance=sw, client=client)
    return render(request, "core/software_form.html", {
        "form": form, "client": client, "title": f"Edit: {sw.get_software_type_display()}"
    })


@login_required
def software_delete(request, pk):
    sw = get_object_or_404(AccountingSoftware, pk=pk)
    client = sw.client
    if not request.user.can_edit:
        messages.error(request, "You do not have permission to delete software configs.")
        return redirect("core:client_detail", pk=client.pk)

    if request.method == "POST":
        label = sw.get_software_type_display()
        sw.delete()
        messages.success(request, f"Software '{label}' removed.")
    return redirect("core:client_detail", pk=client.pk)


# ---------------------------------------------------------------------------
# Meeting Notes
# ---------------------------------------------------------------------------
@login_required
def meeting_note_create(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)

    if request.method == "POST":
        form = MeetingNoteForm(request.POST, client=client)
        if form.is_valid():
            note = form.save(commit=False)
            note.client = client
            note.created_by = request.user
            note.save()
            _log_action(request, "import", f"Added meeting note: {note.title}", note)
            messages.success(request, f"Meeting note '{note.title}' created.")
            return redirect("core:client_detail", pk=client_pk)
    else:
        form = MeetingNoteForm(client=client, initial={"meeting_date": timezone.now().date()})
    return render(request, "core/meeting_note_form.html", {
        "form": form, "client": client, "title": "New Meeting Note"
    })


@login_required
def meeting_note_edit(request, pk):
    note = get_object_or_404(MeetingNote, pk=pk)
    client = note.client

    if request.method == "POST":
        form = MeetingNoteForm(request.POST, instance=note, client=client)
        if form.is_valid():
            form.save()
            messages.success(request, f"Meeting note '{note.title}' updated.")
            return redirect("core:client_detail", pk=client.pk)
    else:
        form = MeetingNoteForm(instance=note, client=client)
    return render(request, "core/meeting_note_form.html", {
        "form": form, "client": client, "title": f"Edit: {note.title}"
    })


@login_required
def meeting_note_detail(request, pk):
    note = get_object_or_404(MeetingNote, pk=pk)
    client = note.client
    return render(request, "core/meeting_note_detail.html", {
        "note": note, "client": client,
    })


@login_required
def meeting_note_delete(request, pk):
    note = get_object_or_404(MeetingNote, pk=pk)
    client = note.client

    if request.method == "POST":
        title = note.title
        note.delete()
        messages.success(request, f"Meeting note '{title}' deleted.")
    return redirect("core:client_detail", pk=client.pk)


@login_required
def meeting_note_toggle_followup(request, pk):
    """HTMX endpoint to toggle follow-up completion."""
    note = get_object_or_404(MeetingNote, pk=pk)
    note.follow_up_completed = not note.follow_up_completed
    note.save(update_fields=["follow_up_completed"])
    return JsonResponse({"completed": note.follow_up_completed})
