"""
Integrations views.

Handles OAuth2 connection flows for Xero, MYOB, and QuickBooks,
trial balance fetching with staged import, and the mapping
review/approval workflow.
"""
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (
    AccountMapping,
    ClientAccountMapping,
    Entity,
    FinancialYear,
    TrialBalanceLine,
)
from .models import AccountingConnection, ImportLog
from .providers import get_provider, get_configured_providers, PROVIDERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

@login_required
def connection_manage(request, entity_pk):
    """Show and manage accounting platform connections for an entity."""
    entity = get_object_or_404(Entity, pk=entity_pk)
    connections = entity.accounting_connections.all()
    configured_providers = get_configured_providers()

    connected_names = set(
        connections.filter(status="active").values_list("provider", flat=True)
    )

    context = {
        "entity": entity,
        "connections": connections,
        "configured_providers": configured_providers,
        "connected_names": connected_names,
    }
    return render(request, "integrations/connection_manage.html", context)


@login_required
def oauth_connect(request, entity_pk, provider_name):
    """Initiate OAuth2 connection to an accounting platform."""
    entity = get_object_or_404(Entity, pk=entity_pk)
    provider = get_provider(provider_name)

    if not provider or not provider.is_configured():
        messages.error(request, f"{provider_name} integration is not configured.")
        return redirect("integrations:connection_manage", entity_pk=entity_pk)

    state = str(uuid.uuid4())
    request.session["oauth_state"] = state
    request.session["oauth_entity_pk"] = str(entity_pk)
    request.session["oauth_provider"] = provider_name

    redirect_uri = request.build_absolute_uri(
        reverse("integrations:oauth_callback")
    )

    params = provider.get_authorize_params(redirect_uri, state)
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{provider.authorize_url}?{query_string}"

    return redirect(auth_url)


@login_required
def oauth_callback(request):
    """Handle OAuth2 callback from the accounting platform."""
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")
    realm_id = request.GET.get("realmId", "")

    expected_state = request.session.get("oauth_state")
    entity_pk = request.session.get("oauth_entity_pk")
    provider_name = request.session.get("oauth_provider")

    if not all([code, state, entity_pk, provider_name]) or state != expected_state:
        messages.error(request, "OAuth authentication failed: invalid state.")
        return redirect("core:entity_list")

    if error:
        messages.error(request, f"OAuth authentication failed: {error}")
        return redirect("integrations:connection_manage", entity_pk=entity_pk)

    provider = get_provider(provider_name)
    entity = get_object_or_404(Entity, pk=entity_pk)

    redirect_uri = request.build_absolute_uri(
        reverse("integrations:oauth_callback")
    )

    try:
        tokens = provider.exchange_code(code, redirect_uri)
        tenants = provider.get_tenants(tokens["access_token"])

        if provider_name == "quickbooks" and realm_id:
            tenant_id = realm_id
            tenant_name = "QuickBooks Company"
        elif len(tenants) == 1:
            tenant_id = tenants[0]["id"]
            tenant_name = tenants[0]["name"]
        elif len(tenants) > 1:
            request.session["oauth_tokens"] = tokens
            request.session["oauth_tenants"] = tenants
            return redirect("integrations:select_tenant", entity_pk=entity_pk)
        else:
            tenant_id = ""
            tenant_name = ""

        AccountingConnection.objects.filter(
            entity=entity, provider=provider_name, status="active"
        ).update(status="disconnected")

        conn = AccountingConnection.objects.create(
            entity=entity,
            provider=provider_name,
            status="active",
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_expires_at=timezone.now() + timedelta(seconds=tokens["expires_in"]),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            connected_by=request.user,
        )

        messages.success(
            request,
            f"Successfully connected to {provider.display_name}"
            + (f" ({tenant_name})" if tenant_name else "")
        )

    except Exception as e:
        logger.error(f"OAuth callback error for {provider_name}: {e}")
        messages.error(request, f"Connection failed: {str(e)}")

    for key in ["oauth_state", "oauth_entity_pk", "oauth_provider", "oauth_tokens", "oauth_tenants"]:
        request.session.pop(key, None)

    return redirect("integrations:connection_manage", entity_pk=entity_pk)


@login_required
def select_tenant(request, entity_pk):
    """Show tenant/organisation selection when multiple are available."""
    entity = get_object_or_404(Entity, pk=entity_pk)
    tenants = request.session.get("oauth_tenants", [])
    provider_name = request.session.get("oauth_provider", "")

    if request.method == "POST":
        tenant_id = request.POST.get("tenant_id", "")
        tenant_name = ""
        for t in tenants:
            if t["id"] == tenant_id:
                tenant_name = t["name"]
                break

        tokens = request.session.get("oauth_tokens", {})

        AccountingConnection.objects.filter(
            entity=entity, provider=provider_name, status="active"
        ).update(status="disconnected")

        AccountingConnection.objects.create(
            entity=entity,
            provider=provider_name,
            status="active",
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            token_expires_at=timezone.now() + timedelta(seconds=tokens.get("expires_in", 1800)),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            connected_by=request.user,
        )

        for key in ["oauth_state", "oauth_entity_pk", "oauth_provider", "oauth_tokens", "oauth_tenants"]:
            request.session.pop(key, None)

        provider = get_provider(provider_name)
        messages.success(request, f"Connected to {provider.display_name} ({tenant_name})")
        return redirect("integrations:connection_manage", entity_pk=entity_pk)

    context = {
        "entity": entity,
        "tenants": tenants,
        "provider_name": provider_name,
    }
    return render(request, "integrations/select_tenant.html", context)


@login_required
@require_POST
def disconnect(request, connection_pk):
    """Disconnect an accounting platform connection."""
    conn = get_object_or_404(AccountingConnection, pk=connection_pk)
    entity_pk = conn.entity_id
    conn.status = "disconnected"
    conn.access_token = ""
    conn.refresh_token = ""
    conn.save()

    messages.success(request, f"Disconnected from {conn.get_provider_display()}.")
    return redirect("integrations:connection_manage", entity_pk=entity_pk)


# ---------------------------------------------------------------------------
# Token refresh helper
# ---------------------------------------------------------------------------

def _ensure_valid_token(connection):
    """Refresh the access token if needed. Returns True if token is valid."""
    if not connection.needs_refresh:
        return True

    provider = get_provider(connection.provider)
    if not provider:
        return False

    try:
        tokens = provider.refresh_tokens(connection.refresh_token)
        connection.access_token = tokens["access_token"]
        connection.refresh_token = tokens["refresh_token"]
        connection.token_expires_at = timezone.now() + timedelta(
            seconds=tokens["expires_in"]
        )
        connection.status = "active"
        connection.last_error = ""
        connection.save()
        return True
    except Exception as e:
        logger.error(f"Token refresh failed for {connection}: {e}")
        connection.status = "expired"
        connection.last_error = str(e)
        connection.save()
        return False


# ---------------------------------------------------------------------------
# Trial Balance Import (staged with learning)
# ---------------------------------------------------------------------------

@login_required
def import_from_cloud(request, fy_pk):
    """
    Pull trial balance from connected accounting platform.
    Shows a review/approval page with pre-populated mappings from
    the learning system before committing the import.
    """
    fy = get_object_or_404(FinancialYear, pk=fy_pk)
    entity = fy.entity

    if fy.is_locked:
        messages.error(request, "Cannot import into a finalised financial year.")
        return redirect("core:financial_year_detail", pk=fy_pk)

    connections = entity.accounting_connections.filter(status="active")
    if not connections.exists():
        messages.warning(
            request,
            "No accounting platform connected. "
            "Connect Xero, MYOB, or QuickBooks first."
        )
        return redirect("integrations:connection_manage", entity_pk=entity.pk)

    connection = connections.first()

    if not _ensure_valid_token(connection):
        messages.error(
            request,
            f"Connection to {connection.get_provider_display()} has expired. "
            "Please reconnect."
        )
        return redirect("integrations:connection_manage", entity_pk=entity.pk)

    provider = get_provider(connection.provider)

    try:
        as_at_date = fy.end_date
        raw_lines = provider.fetch_trial_balance(
            connection.access_token, connection.tenant_id, as_at_date
        )

        if not raw_lines:
            messages.warning(request, "No trial balance data returned from the provider.")
            return redirect("core:financial_year_detail", pk=fy_pk)

        staged_lines = _apply_learned_mappings(entity, raw_lines)

        request.session["staged_import"] = {
            "fy_pk": str(fy_pk),
            "connection_pk": str(connection.pk),
            "as_at_date": as_at_date.isoformat(),
            "provider_name": provider.display_name,
            "lines": staged_lines,
        }

        connection.last_sync_at = timezone.now()
        connection.save(update_fields=["last_sync_at"])

        return redirect("integrations:review_import", fy_pk=fy_pk)

    except Exception as e:
        logger.error(f"Cloud import failed: {e}")
        connection.last_error = str(e)
        connection.save(update_fields=["last_error"])
        messages.error(request, f"Import failed: {str(e)}")
        return redirect("core:financial_year_detail", pk=fy_pk)


@login_required
def review_import(request, fy_pk):
    """
    Review page showing fetched trial balance lines with pre-populated
    account mappings from the learning system. Accountant can approve,
    adjust, or reject individual mappings before committing.
    """
    fy = get_object_or_404(FinancialYear, pk=fy_pk)
    staged = request.session.get("staged_import")

    if not staged or staged.get("fy_pk") != str(fy_pk):
        messages.error(request, "No staged import data found. Please pull again.")
        return redirect("core:financial_year_detail", pk=fy_pk)

    lines = staged["lines"]

    standard_accounts = list(
        AccountMapping.objects.values("id", "standard_code", "line_item_label", "statement_section")
        .order_by("financial_statement", "display_order")
    )
    for sa in standard_accounts:
        sa["id"] = str(sa["id"])

    total = len(lines)
    auto_mapped = sum(1 for l in lines if l.get("mapped_id"))
    unmapped = total - auto_mapped

    context = {
        "fy": fy,
        "lines": lines,
        "standard_accounts_json": json.dumps(standard_accounts),
        "total": total,
        "auto_mapped": auto_mapped,
        "unmapped": unmapped,
        "provider_name": staged.get("provider_name", "Cloud"),
        "as_at_date": staged.get("as_at_date", ""),
    }
    return render(request, "integrations/review_import.html", context)


@login_required
@require_POST
def commit_import(request, fy_pk):
    """
    Commit the reviewed import. Creates TrialBalanceLine records and
    updates ClientAccountMapping (the learning system) with any new
    or changed mappings.
    """
    fy = get_object_or_404(FinancialYear, pk=fy_pk)
    staged = request.session.get("staged_import")

    if not staged or staged.get("fy_pk") != str(fy_pk):
        messages.error(request, "No staged import data found.")
        return redirect("core:financial_year_detail", pk=fy_pk)

    entity = fy.entity
    staged_lines = staged["lines"]
    imported = 0
    unmapped = 0
    errors = []

    fy.trial_balance_lines.filter(is_adjustment=False).delete()

    for i, line in enumerate(staged_lines):
        mapping_id = request.POST.get(f"mapping_{i}", "").strip()
        mapped_item = None

        if mapping_id:
            try:
                mapped_item = AccountMapping.objects.get(pk=mapping_id)
            except AccountMapping.DoesNotExist:
                pass

        try:
            opening = Decimal(str(line.get("opening_balance", "0")))
            debit = Decimal(str(line.get("debit", "0")))
            credit = Decimal(str(line.get("credit", "0")))
            closing = opening + debit - credit

            TrialBalanceLine.objects.create(
                financial_year=fy,
                account_code=line["account_code"],
                account_name=line["account_name"],
                opening_balance=opening,
                debit=debit,
                credit=credit,
                closing_balance=closing,
                mapped_line_item=mapped_item,
                is_adjustment=False,
            )

            # Update the learning system
            ClientAccountMapping.objects.update_or_create(
                entity=entity,
                client_account_code=line["account_code"],
                defaults={
                    "client_account_name": line["account_name"],
                    "mapped_line_item": mapped_item,
                },
            )

            imported += 1
            if not mapped_item:
                unmapped += 1

        except Exception as e:
            errors.append(f"Line {i + 1} ({line.get('account_code', '?')}): {str(e)}")

    # Log the import
    connection_pk = staged.get("connection_pk")
    if connection_pk:
        try:
            connection = AccountingConnection.objects.get(pk=connection_pk)
            ImportLog.objects.create(
                connection=connection,
                financial_year=fy,
                imported_by=request.user,
                lines_imported=imported,
                lines_unmapped=unmapped,
                errors=errors,
                as_at_date=staged.get("as_at_date"),
            )
        except AccountingConnection.DoesNotExist:
            pass

    request.session.pop("staged_import", None)

    messages.success(
        request,
        f"Imported {imported} lines from cloud. "
        f"{unmapped} unmapped accounts need attention."
    )
    if errors:
        for err in errors[:5]:
            messages.warning(request, err)

    return redirect("core:financial_year_detail", pk=fy_pk)


# ---------------------------------------------------------------------------
# Learning system helpers
# ---------------------------------------------------------------------------

def _apply_learned_mappings(entity, raw_lines):
    """
    Look up existing ClientAccountMapping records for this entity and
    pre-populate the mapped_line_item for each raw line.
    """
    existing_mappings = {
        cam.client_account_code: cam
        for cam in ClientAccountMapping.objects.filter(entity=entity)
        .select_related("mapped_line_item")
    }

    staged = []
    for line in raw_lines:
        code = line["account_code"]
        cam = existing_mappings.get(code)

        staged_line = {
            "account_code": code,
            "account_name": line["account_name"],
            "opening_balance": str(line["opening_balance"]),
            "debit": str(line["debit"]),
            "credit": str(line["credit"]),
            "mapped_id": "",
            "mapped_label": "",
            "confidence": "new",
        }

        if cam and cam.mapped_line_item:
            staged_line["mapped_id"] = str(cam.mapped_line_item.pk)
            staged_line["mapped_label"] = (
                f"{cam.mapped_line_item.standard_code} - "
                f"{cam.mapped_line_item.line_item_label}"
            )
            staged_line["confidence"] = "learned"

        staged.append(staged_line)

    return staged


# ---------------------------------------------------------------------------
# Xero Practice Manager (XPM) Integration
# ---------------------------------------------------------------------------

@login_required
def xpm_dashboard(request):
    """XPM integration dashboard: connection status, sync history, manual trigger."""
    from .models import XPMConnection, XPMSyncLog

    connection = XPMConnection.objects.filter(status="active").first()
    if not connection:
        connection = XPMConnection.objects.first()

    sync_logs = XPMSyncLog.objects.all()[:20] if connection else []

    # Check if Xero credentials are configured
    xero_configured = bool(
        getattr(settings, "XERO_CLIENT_ID", "") and
        getattr(settings, "XERO_CLIENT_SECRET", "")
    )

    context = {
        "connection": connection,
        "sync_logs": sync_logs,
        "xero_configured": xero_configured,
    }
    return render(request, "integrations/xpm_dashboard.html", context)


@login_required
def xpm_connect(request):
    """Initiate OAuth2 connection to Xero for Practice Manager access."""
    import uuid as uuid_mod

    state = str(uuid_mod.uuid4())
    request.session["xpm_oauth_state"] = state

    client_id = getattr(settings, "XERO_CLIENT_ID", "")
    redirect_uri = request.build_absolute_uri(
        reverse("integrations:xpm_callback")
    )

    # XPM requires practicemanager scope in addition to standard Xero scopes
    scopes = "openid profile email practicemanager offline_access"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "access_type": "offline",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"https://login.xero.com/identity/connect/authorize?{query_string}"

    return redirect(auth_url)


@login_required
def xpm_callback(request):
    """Handle OAuth2 callback for XPM connection."""
    from .models import XPMConnection

    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")

    expected_state = request.session.get("xpm_oauth_state")

    if error:
        messages.error(request, f"XPM connection failed: {error}")
        return redirect("integrations:xpm_dashboard")

    if not code or state != expected_state:
        messages.error(request, "XPM connection failed: invalid state.")
        return redirect("integrations:xpm_dashboard")

    client_id = getattr(settings, "XERO_CLIENT_ID", "")
    client_secret = getattr(settings, "XERO_CLIENT_SECRET", "")
    redirect_uri = request.build_absolute_uri(
        reverse("integrations:xpm_callback")
    )

    try:
        import requests as req
        # Exchange code for tokens
        resp = req.post(
            "https://login.xero.com/identity/connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        tokens = resp.json()

        # Get tenants
        tenant_resp = req.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=15,
        )
        tenant_resp.raise_for_status()
        tenants = tenant_resp.json()

        if not tenants:
            messages.error(request, "No Xero organisations found.")
            return redirect("integrations:xpm_dashboard")

        # Use the first tenant (or the practice manager tenant)
        tenant = tenants[0]
        tenant_id = tenant.get("tenantId", "")
        tenant_name = tenant.get("tenantName", "Unknown")

        # If multiple tenants, store in session for selection
        if len(tenants) > 1:
            request.session["xpm_tokens"] = tokens
            request.session["xpm_tenants"] = [
                {"id": t["tenantId"], "name": t.get("tenantName", "Unknown")}
                for t in tenants
            ]
            return redirect("integrations:xpm_select_tenant")

        # Deactivate existing connections
        XPMConnection.objects.filter(status="active").update(status="disconnected")

        # Create new connection
        conn = XPMConnection.objects.create(
            status="active",
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", ""),
            token_expires_at=timezone.now() + timedelta(
                seconds=tokens.get("expires_in", 1800)
            ),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            connected_by=request.user,
        )

        messages.success(request, f"Connected to Xero Practice Manager ({tenant_name})")

    except Exception as e:
        logger.error(f"XPM OAuth callback error: {e}")
        messages.error(request, f"XPM connection failed: {str(e)}")

    request.session.pop("xpm_oauth_state", None)
    return redirect("integrations:xpm_dashboard")


@login_required
def xpm_select_tenant(request):
    """Select which Xero tenant to use for XPM."""
    from .models import XPMConnection

    tenants = request.session.get("xpm_tenants", [])
    tokens = request.session.get("xpm_tokens", {})

    if request.method == "POST":
        tenant_id = request.POST.get("tenant_id", "")
        tenant_name = ""
        for t in tenants:
            if t["id"] == tenant_id:
                tenant_name = t["name"]
                break

        XPMConnection.objects.filter(status="active").update(status="disconnected")

        XPMConnection.objects.create(
            status="active",
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            token_expires_at=timezone.now() + timedelta(
                seconds=tokens.get("expires_in", 1800)
            ),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            connected_by=request.user,
        )

        for key in ["xpm_tokens", "xpm_tenants", "xpm_oauth_state"]:
            request.session.pop(key, None)

        messages.success(request, f"Connected to Xero Practice Manager ({tenant_name})")
        return redirect("integrations:xpm_dashboard")

    return render(request, "integrations/xpm_select_tenant.html", {
        "tenants": tenants,
    })


@login_required
@require_POST
def xpm_disconnect(request):
    """Disconnect from XPM."""
    from .models import XPMConnection

    XPMConnection.objects.filter(status="active").update(
        status="disconnected",
        access_token="",
        refresh_token="",
    )
    messages.success(request, "Disconnected from Xero Practice Manager.")
    return redirect("integrations:xpm_dashboard")


@login_required
@require_POST
def xpm_sync_now(request):
    """Trigger a manual full sync from XPM."""
    from .models import XPMConnection
    from .xpm_sync import run_full_sync

    connection = XPMConnection.objects.filter(status="active").first()
    if not connection:
        messages.error(request, "No active XPM connection. Connect first.")
        return redirect("integrations:xpm_dashboard")

    try:
        sync_log = run_full_sync(connection, user=request.user)

        if sync_log.status == "completed":
            messages.success(
                request,
                f"XPM sync completed: {sync_log.clients_created} clients created, "
                f"{sync_log.clients_updated} updated, "
                f"{sync_log.entities_created} entities created."
            )
        elif sync_log.status == "partial":
            messages.warning(
                request,
                f"XPM sync completed with errors: {sync_log.clients_created} created, "
                f"{sync_log.clients_updated} updated. "
                f"{len(sync_log.errors)} errors."
            )
        else:
            messages.error(request, f"XPM sync failed: {sync_log.errors}")

    except Exception as e:
        messages.error(request, f"XPM sync failed: {str(e)}")

    return redirect("integrations:xpm_dashboard")
