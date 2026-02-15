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
    AccountMapping, ClientAccountMapping, AdjustingJournal,
    JournalLine, GeneratedDocument, AuditLog, EntityOfficer,
)
from .forms import (
    ClientForm, EntityForm, FinancialYearForm,
    TrialBalanceUploadForm, AccountMappingForm,
    AdjustingJournalForm, JournalLineFormSet,
    EntityOfficerForm,
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
        return redirect("core:dashboard")

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
    context = {"client": client, "entities": entities}
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

    context = {
        "fy": fy,
        "entity": fy.entity,
        "client": fy.entity.client,
        "tb_lines": tb_lines,
        "adjustments": adjustments,
        "unmapped_count": unmapped_count,
        "documents": documents,
        "total_debit": total_debit,
        "total_credit": total_credit,
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

        # Try to find existing mapping for this entity
        mapping = ClientAccountMapping.objects.filter(
            entity=entity, client_account_code=account_code
        ).first()

        mapped_item = mapping.mapped_line_item if mapping else None

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
# Adjusting Journals
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
        messages.error(request, "Cannot add adjustments to a finalised year.")
        return redirect("core:financial_year_detail", pk=pk)

    if not request.user.can_edit:
        messages.error(request, "You do not have permission.")
        return redirect("core:financial_year_detail", pk=pk)

    if request.method == "POST":
        form = AdjustingJournalForm(request.POST)
        formset = JournalLineFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            journal = form.save(commit=False)
            journal.financial_year = fy
            journal.created_by = request.user
            journal.save()

            formset.instance = journal
            lines = formset.save()

            # Validate debits = credits
            total_dr = sum(l.debit for l in lines)
            total_cr = sum(l.credit for l in lines)
            if total_dr != total_cr:
                journal.delete()
                messages.error(request, f"Journal does not balance: Dr {total_dr} != Cr {total_cr}")
                return render(request, "core/adjustment_form.html", {
                    "form": form, "formset": formset, "fy": fy
                })

            # Create adjustment trial balance lines
            for line in lines:
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

            _log_action(request, "adjustment", f"Created adjustment: {journal.description}", journal)
            messages.success(request, "Adjusting journal created.")
            return redirect("core:financial_year_detail", pk=pk)
    else:
        form = AdjustingJournalForm()
        formset = JournalLineFormSet()

    return render(request, "core/adjustment_form.html", {
        "form": form, "formset": formset, "fy": fy
    })


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

    from .docgen import generate_financial_statements

    try:
        buffer = generate_financial_statements(fy.pk)
    except Exception as e:
        messages.error(request, f"Document generation failed: {e}")
        return redirect("core:financial_year_detail", pk=pk)

    # Build filename
    entity_name = fy.entity.entity_name.replace(" ", "_")
    filename = f"{entity_name}_Financial_Statements_{fy.year_label}.docx"

    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Log the generation
    _log_action(request, "generate", f"Generated financial statements for {fy}", fy)

    # Save record
    GeneratedDocument.objects.create(
        financial_year=fy,
        file_format="docx",
        generated_by=request.user,
        file_path=filename,
    )

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
