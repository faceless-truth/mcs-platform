"""
Email Ingestion Service for Bank Statement Processing.

Supports two modes:
1. Microsoft Graph API (preferred for M365/Outlook)
2. IMAP polling (fallback)

Reads emails from bankstatements@mcands.com.au, extracts PDF attachments,
and feeds them into the bank statement processing pipeline.
"""
import base64
import email
import imaplib
import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

from .models import PendingTransaction, ReviewActivity, ReviewJob, TransactionPattern

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client / Entity matching
# ---------------------------------------------------------------------------

def _match_entity_from_email(sender_email, subject, body=""):
    """
    Attempt to match an incoming email to a known Entity.
    Tries multiple strategies:
    1. Sender email matches client contact_email
    2. Subject line contains entity name or ABN
    3. Body contains entity name
    Returns (Entity, Client) or (None, None).
    """
    from core.models import Client, Entity

    # Strategy 1: Match sender email to client
    clients = Client.objects.filter(contact_email__iexact=sender_email)
    if clients.exists():
        client = clients.first()
        # Return the first active entity for this client
        entity = client.entities.first()
        if entity:
            return entity, client

    # Strategy 2: Search subject for entity name
    entities = Entity.objects.select_related("client").all()
    subject_lower = subject.lower() if subject else ""
    body_lower = body.lower() if body else ""

    for entity in entities:
        name_lower = entity.entity_name.lower()
        if name_lower in subject_lower or name_lower in body_lower:
            return entity, entity.client

    # Strategy 3: Search for ABN in subject or body
    abn_pattern = re.compile(r"\b(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})\b")
    for text in [subject, body]:
        if not text:
            continue
        matches = abn_pattern.findall(text)
        for match in matches:
            abn_clean = match.replace(" ", "")
            try:
                entity = Entity.objects.select_related("client").get(abn=abn_clean)
                return entity, entity.client
            except Entity.DoesNotExist:
                continue

    return None, None


# ---------------------------------------------------------------------------
# Microsoft Graph API email fetching
# ---------------------------------------------------------------------------

def _get_graph_access_token():
    """Get an access token for Microsoft Graph API using client credentials."""
    tenant_id = getattr(settings, "MS_GRAPH_TENANT_ID", "")
    client_id = getattr(settings, "MS_GRAPH_CLIENT_ID", "")
    client_secret = getattr(settings, "MS_GRAPH_CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        return None

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    resp = requests.post(url, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json().get("access_token")


def fetch_emails_graph(mailbox="bankstatements@mcands.com.au", max_emails=20):
    """
    Fetch unread emails with PDF attachments from the specified mailbox
    using Microsoft Graph API.
    Returns list of dicts: {sender, subject, body, attachments: [{name, content_bytes}]}
    """
    token = _get_graph_access_token()
    if not token:
        logger.warning("Microsoft Graph API not configured")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Fetch unread messages
    url = (
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages"
        f"?$filter=isRead eq false and hasAttachments eq true"
        f"&$top={max_emails}"
        f"&$orderby=receivedDateTime desc"
        f"&$select=id,subject,from,body,receivedDateTime"
    )
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    messages = resp.json().get("value", [])

    results = []
    for msg in messages:
        msg_id = msg["id"]
        sender = msg.get("from", {}).get("emailAddress", {}).get("address", "")
        subject = msg.get("subject", "")
        body = msg.get("body", {}).get("content", "")

        # Fetch attachments
        att_url = (
            f"https://graph.microsoft.com/v1.0/users/{mailbox}"
            f"/messages/{msg_id}/attachments"
        )
        att_resp = requests.get(att_url, headers=headers, timeout=30)
        att_resp.raise_for_status()
        attachments = []

        for att in att_resp.json().get("value", []):
            name = att.get("name", "")
            content_type = att.get("contentType", "")
            if name.lower().endswith(".pdf") or "pdf" in content_type.lower():
                content_b64 = att.get("contentBytes", "")
                if content_b64:
                    attachments.append({
                        "name": name,
                        "content_bytes": base64.b64decode(content_b64),
                        "content_b64": content_b64,
                    })

        if attachments:
            results.append({
                "msg_id": msg_id,
                "sender": sender,
                "subject": subject,
                "body": body,
                "attachments": attachments,
            })

        # Mark as read
        patch_url = (
            f"https://graph.microsoft.com/v1.0/users/{mailbox}"
            f"/messages/{msg_id}"
        )
        requests.patch(
            patch_url, headers=headers,
            json={"isRead": True}, timeout=10,
        )

    return results


# ---------------------------------------------------------------------------
# IMAP email fetching (fallback)
# ---------------------------------------------------------------------------

def fetch_emails_imap():
    """
    Fetch unread emails with PDF attachments via IMAP.
    Returns same format as fetch_emails_graph.
    """
    host = getattr(settings, "IMAP_HOST", "")
    port = getattr(settings, "IMAP_PORT", 993)
    username = getattr(settings, "IMAP_USERNAME", "")
    password = getattr(settings, "IMAP_PASSWORD", "")

    if not all([host, username, password]):
        logger.warning("IMAP not configured")
        return []

    results = []
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(username, password)
        mail.select("INBOX")

        # Search for unread messages
        status, msg_ids = mail.search(None, "UNSEEN")
        if status != "OK":
            return []

        for msg_id in msg_ids[0].split()[:20]:  # Max 20
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            sender = email.utils.parseaddr(msg.get("From", ""))[1]
            subject = msg.get("Subject", "")
            body = ""

            # Extract body
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

            # Extract PDF attachments
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    filename = part.get_filename()
                    if filename and filename.lower().endswith(".pdf"):
                        content = part.get_payload(decode=True)
                        if content:
                            attachments.append({
                                "name": filename,
                                "content_bytes": content,
                                "content_b64": base64.b64encode(content).decode("ascii"),
                            })

            if attachments:
                results.append({
                    "msg_id": msg_id.decode(),
                    "sender": sender,
                    "subject": subject,
                    "body": body,
                    "attachments": attachments,
                })

            # Mark as read (IMAP flag)
            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.logout()
    except Exception as e:
        logger.error(f"IMAP fetch failed: {e}")

    return results


# ---------------------------------------------------------------------------
# PDF Transaction Extraction (OpenAI)
# ---------------------------------------------------------------------------

def extract_transactions_from_pdf(pdf_b64, filename="statement.pdf"):
    """
    Use OpenAI to extract transactions from a bank statement PDF.
    Returns dict with: opening_balance, closing_balance, account_name,
    bsb, account_number, period_start, period_end, transactions[]
    """
    from openai import OpenAI

    client = OpenAI()

    system_prompt = (
        "You are a bank statement parser for an Australian accounting firm. "
        "Extract ALL transactions from the provided bank statement PDF. "
        "For each transaction, extract: date (DD/MM/YYYY format), "
        "description (the full transaction description as shown), "
        "amount (positive for credits/deposits, negative for debits/withdrawals). "
        "Return a JSON object with keys: opening_balance (number), "
        "closing_balance (number), account_name (string), bsb (string), "
        "account_number (string), period_start (string DD/MM/YYYY), "
        "period_end (string DD/MM/YYYY), "
        "transactions (array of {date, description, amount}). "
        "Return ONLY valid JSON."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "file",
                            "file": {
                                "filename": filename,
                                "file_data": f"data:application/pdf;base64,{pdf_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract ALL transactions from this bank statement PDF. Return valid JSON only.",
                        },
                    ],
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        return data

    except Exception as e:
        logger.error(f"PDF extraction failed for {filename}: {e}")
        return None


# ---------------------------------------------------------------------------
# AI Transaction Classification
# ---------------------------------------------------------------------------

CHART_OF_ACCOUNTS = """CHART OF ACCOUNTS:
INCOME: 4-1000 Sales Revenue (GST), 4-1100 Service Revenue (GST), 4-1200 Interest Income (ITS), 4-1300 Other Income (GST), 4-2000 Rental Income (GST)
EXPENSES: 6-1000 Accounting Fees (GST), 6-1100 Advertising (GST), 6-1200 Bank Charges (ITS), 6-1300 Cleaning (GST), 6-1400 Computer/IT (GST), 6-1600 Electricity/Gas (GST), 6-1700 Entertainment (GST), 6-1800 Fuel & Oil (GST), 6-1900 General Expenses (GST), 6-2000 Insurance (ITS), 6-2100 Interest Paid (ITS), 6-2200 Legal Fees (GST), 6-2300 Motor Vehicle (GST), 6-2400 Office Supplies (GST), 6-2500 Postage (GST), 6-2600 Printing (GST), 6-2700 Rates & Taxes (ITS), 6-2800 Rent (GST), 6-2900 Repairs & Maintenance (GST), 6-3000 Subscriptions (GST), 6-3100 Superannuation (ITS), 6-3200 Telephone (GST), 6-3300 Tools & Equipment (GST), 6-3400 Travel (GST), 6-3500 Wages (ITS), 6-3600 Workers Comp (ITS), 6-3700 Uniforms (GST)
BALANCE SHEET: 2-1000 Director/Beneficiary Loan (N-T), 1-1000 Cash at Bank (N-T), 2-2000 PAYG Withholding (ITS), 2-3000 GST Collected/Paid (N-T)

RULES:
- Fuel (BP, Shell, Ampol, EG Group, 7-Eleven, United, Caltex) = 6-1800, GST
- Hardware (Bunnings, Total Tools) = 6-3300, GST
- Insurance = 6-2000, ITS
- ATO payments = 2-2000, ITS
- Bank fees = 6-1200, ITS
- Telco (Telstra, Optus) = 6-3200, GST
- Internal transfers = 2-1000, N-T
- Customer payments/deposits = 4-1000, GST
- Interest earned = 4-1200, ITS
- Rent/lease = 6-2800, GST
- Utilities (AGL, Origin) = 6-1600, GST
- Wages = 6-3500, ITS
- Super = 6-3100, ITS
- Software (Microsoft, Google, Xero) = 6-1400, GST

TAX TYPE CODES:
- GST = GST on Income (for income) or GST on Expenses (for expenses)
- ITS = Input Taxed (no GST component)
- N-T = Not Reportable (balance sheet items, internal transfers)
- GST-Free = GST Free Income or GST Free Expenses

CONFIDENCE: 5=Certain, 4=Very likely, 3=Probable, 2=Uncertain, 1=Unknown"""


def classify_transactions(transactions, entity=None, is_gst_registered=True):
    """
    Classify a list of transactions using:
    1. Learning database (per-client patterns) — highest priority
    2. OpenAI API — for unknown transactions

    For GST-registered clients, calculates GST component.
    For non-GST clients, all tax types default to BAS Excluded.

    Returns list of dicts with classification results.
    """
    results = []
    unknown_txns = []
    unknown_indices = []

    # Step 1: Check learning database for known patterns
    for i, txn in enumerate(transactions):
        desc = txn.get("description", "")
        desc_normalised = _normalise_description(desc)

        pattern = _find_pattern(desc_normalised, entity)
        if pattern:
            tax_type = pattern.tax_type
            if not is_gst_registered and tax_type in ("GST on Income", "GST on Expenses"):
                tax_type = "BAS Excluded"

            results.append({
                "index": i,
                "account_code": pattern.account_code,
                "account_name": pattern.account_name,
                "tax_type": tax_type,
                "confidence": 5,
                "reasoning": f"Matched learning pattern (used {pattern.usage_count}x)",
                "from_learning": True,
            })
        else:
            results.append(None)  # Placeholder
            unknown_txns.append(txn)
            unknown_indices.append(i)

    # Step 2: AI classify unknown transactions in batches
    if unknown_txns:
        ai_results = _ai_classify_batch(unknown_txns, is_gst_registered)
        for idx, ai_result in zip(unknown_indices, ai_results):
            results[idx] = {
                "index": idx,
                "account_code": ai_result.get("accountCode", "6-1900"),
                "account_name": ai_result.get("accountName", "General Expenses"),
                "tax_type": _map_tax_type(
                    ai_result.get("taxType", "GST"),
                    transactions[idx].get("amount", 0),
                    is_gst_registered,
                ),
                "confidence": ai_result.get("confidence", 1),
                "reasoning": ai_result.get("reasoning", ""),
                "from_learning": False,
            }

    return results


def _normalise_description(desc):
    """Normalise a transaction description for pattern matching."""
    # Remove dates, reference numbers, extra whitespace
    desc = re.sub(r"\d{2}/\d{2}/\d{2,4}", "", desc)
    desc = re.sub(r"\b\d{6,}\b", "", desc)  # Remove long numbers
    desc = re.sub(r"\s+", " ", desc).strip().upper()
    return desc


def _find_pattern(normalised_desc, entity=None):
    """
    Find a matching pattern in the learning database.
    Checks entity-specific patterns first, then global patterns.
    """
    if not normalised_desc:
        return None

    # Entity-specific pattern (exact match)
    if entity:
        pattern = TransactionPattern.objects.filter(
            entity=entity,
            description_pattern=normalised_desc,
        ).first()
        if pattern:
            return pattern

    # Entity-specific pattern (contains match)
    if entity:
        patterns = TransactionPattern.objects.filter(entity=entity)
        for p in patterns:
            if p.description_pattern in normalised_desc or normalised_desc in p.description_pattern:
                return p

    # Global pattern (exact match)
    pattern = TransactionPattern.objects.filter(
        entity__isnull=True,
        description_pattern=normalised_desc,
    ).first()
    if pattern:
        return pattern

    return None


def _map_tax_type(ai_tax_type, amount, is_gst_registered):
    """Map the AI's short tax type code to the full tax type label."""
    if not is_gst_registered:
        return "BAS Excluded"

    ai_tax_upper = (ai_tax_type or "").upper().strip()
    is_income = float(amount) >= 0

    mapping = {
        "GST": "GST on Income" if is_income else "GST on Expenses",
        "GST ON INCOME": "GST on Income",
        "GST ON EXPENSES": "GST on Expenses",
        "ITS": "Input Taxed",
        "INPUT TAXED": "Input Taxed",
        "N-T": "N-T",
        "NOT REPORTABLE": "N-T",
        "GST-FREE": "GST Free Income" if is_income else "GST Free Expenses",
        "GST FREE": "GST Free Income" if is_income else "GST Free Expenses",
        "GST FREE INCOME": "GST Free Income",
        "GST FREE EXPENSES": "GST Free Expenses",
        "BAS EXCLUDED": "BAS Excluded",
    }
    return mapping.get(ai_tax_upper, "GST on Expenses" if not is_income else "GST on Income")


def _ai_classify_batch(transactions, is_gst_registered=True, batch_size=15):
    """
    Classify transactions using OpenAI API.
    Processes in batches of batch_size.
    """
    from openai import OpenAI

    client = OpenAI()
    all_results = []

    for i in range(0, len(transactions), batch_size):
        batch = transactions[i:i + batch_size]

        txn_list = "\n".join(
            f"{j + 1}. Date: {t.get('date', '')}, "
            f"Desc: \"{t.get('description', '')}\", "
            f"Amount: ${abs(float(t.get('amount', 0))):.2f} "
            f"({'CREDIT' if float(t.get('amount', 0)) >= 0 else 'DEBIT'})"
            for j, t in enumerate(batch)
        )

        gst_context = ""
        if is_gst_registered:
            gst_context = (
                "\n\nGST CONTEXT: This client IS registered for GST. "
                "Assign appropriate tax types (GST, ITS, N-T, GST-Free) "
                "based on the nature of each transaction."
            )
        else:
            gst_context = (
                "\n\nGST CONTEXT: This client is NOT registered for GST. "
                "All tax types should be 'BAS Excluded'."
            )

        prompt = (
            f"Classify these Australian bank transactions:\n\n"
            f"{CHART_OF_ACCOUNTS}{gst_context}\n\n"
            f"TRANSACTIONS:\n{txn_list}\n\n"
            f"Return JSON: {{\"classifications\": ["
            f"{{\"accountCode\": str, \"accountName\": str, "
            f"\"taxType\": str, \"confidence\": int 1-5, "
            f"\"reasoning\": str}}]}}"
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You are an Australian accounting AI assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            parsed = json.loads(content)
            classifications = (
                parsed.get("classifications")
                or parsed.get("results")
                or parsed.get("transactions")
                or []
            )

            # Pad with defaults if AI returned fewer results
            while len(classifications) < len(batch):
                classifications.append({
                    "accountCode": "6-1900",
                    "accountName": "General Expenses",
                    "taxType": "GST",
                    "confidence": 1,
                    "reasoning": "No classification returned",
                })

            all_results.extend(classifications[:len(batch)])

        except Exception as e:
            logger.error(f"AI classification failed: {e}")
            # Return defaults for the batch
            for _ in batch:
                all_results.append({
                    "accountCode": "6-1900",
                    "accountName": "General Expenses",
                    "taxType": "GST",
                    "confidence": 1,
                    "reasoning": f"Classification error: {str(e)}",
                })

    return all_results


# ---------------------------------------------------------------------------
# Main Processing Pipeline
# ---------------------------------------------------------------------------

def process_bank_statement_email(email_data):
    """
    Process a single bank statement email through the full pipeline:
    1. Match to entity
    2. Extract transactions from PDF
    3. Classify with learning DB + AI
    4. Calculate GST
    5. Create ReviewJob + PendingTransactions

    Args:
        email_data: dict with sender, subject, body, attachments
    Returns:
        ReviewJob or None
    """
    sender = email_data.get("sender", "")
    subject = email_data.get("subject", "")
    body = email_data.get("body", "")
    attachments = email_data.get("attachments", [])

    if not attachments:
        logger.warning(f"No PDF attachments in email from {sender}: {subject}")
        return None

    # Match to entity
    entity, client = _match_entity_from_email(sender, subject, body)
    client_name = entity.entity_name if entity else (
        client.name if client else _extract_client_name(subject, sender)
    )
    is_gst_registered = entity.is_gst_registered if entity else True

    logger.info(
        f"Processing bank statement for {client_name} "
        f"(GST registered: {is_gst_registered})"
    )

    # Process each PDF attachment
    for attachment in attachments:
        pdf_b64 = attachment.get("content_b64", "")
        if not pdf_b64 and attachment.get("content_bytes"):
            pdf_b64 = base64.b64encode(attachment["content_bytes"]).decode("ascii")

        filename = attachment.get("name", "statement.pdf")

        # Extract transactions
        extracted = extract_transactions_from_pdf(pdf_b64, filename)
        if not extracted or not extracted.get("transactions"):
            logger.error(f"No transactions extracted from {filename}")
            continue

        transactions = extracted["transactions"]

        # Classify transactions
        classifications = classify_transactions(
            transactions, entity=entity, is_gst_registered=is_gst_registered
        )

        # Create ReviewJob
        job = ReviewJob.objects.create(
            entity=entity,
            client_name=client_name,
            file_name=filename,
            submitted_by=sender,
            source="email",
            total_transactions=len(transactions),
            auto_coded_count=len(transactions),
            flagged_count=sum(
                1 for c in classifications if c and c.get("confidence", 0) < 5
            ),
            confirmed_count=0,
            is_gst_registered=is_gst_registered,
            bank_account_name=extracted.get("account_name", ""),
            bsb=extracted.get("bsb", ""),
            account_number=extracted.get("account_number", ""),
            period_start=extracted.get("period_start", ""),
            period_end=extracted.get("period_end", ""),
            opening_balance=Decimal(str(extracted.get("opening_balance", 0))),
            closing_balance=Decimal(str(extracted.get("closing_balance", 0))),
        )

        # Create PendingTransactions with GST calculations
        for txn, cls in zip(transactions, classifications):
            if cls is None:
                cls = {
                    "account_code": "6-1900",
                    "account_name": "General Expenses",
                    "tax_type": "GST on Expenses",
                    "confidence": 1,
                    "reasoning": "",
                    "from_learning": False,
                }

            amount = Decimal(str(txn.get("amount", 0)))
            tax_type = cls.get("tax_type", "")

            # Calculate GST
            abs_amount = abs(amount)
            if is_gst_registered and tax_type in ("GST on Income", "GST on Expenses"):
                gst_amount = (abs_amount / Decimal("11")).quantize(Decimal("0.01"))
                net_amount = (abs_amount - gst_amount).quantize(Decimal("0.01"))
            else:
                gst_amount = Decimal("0.00")
                net_amount = abs_amount

            # Auto-confirm high-confidence items from learning DB
            is_auto_confirmed = (
                cls.get("from_learning", False) and cls.get("confidence", 0) >= 5
            )

            PendingTransaction.objects.create(
                job=job,
                date=txn.get("date", ""),
                description=txn.get("description", ""),
                amount=amount,
                gst_amount=gst_amount,
                net_amount=net_amount,
                ai_suggested_code=cls.get("account_code", ""),
                ai_suggested_name=cls.get("account_name", ""),
                ai_suggested_tax_type=tax_type,
                ai_confidence=cls.get("confidence", 1),
                ai_reasoning=cls.get("reasoning", ""),
                from_learning=cls.get("from_learning", False),
                is_confirmed=is_auto_confirmed,
                confirmed_code=cls.get("account_code", "") if is_auto_confirmed else "",
                confirmed_name=cls.get("account_name", "") if is_auto_confirmed else "",
                confirmed_tax_type=tax_type if is_auto_confirmed else "",
            )

        # Update confirmed count for auto-confirmed items
        job.confirmed_count = job.transactions.filter(is_confirmed=True).count()
        if job.confirmed_count > 0:
            job.status = "in_progress"
        job.save()

        # Log activity
        ReviewActivity.objects.create(
            activity_type="email_processed",
            title="Bank statement processed",
            description=(
                f"{client_name} — {len(transactions)} transactions extracted, "
                f"{job.confirmed_count} auto-confirmed"
                f"{' (GST registered)' if is_gst_registered else ' (not GST registered)'}"
            ),
        )

        logger.info(
            f"Created review job {job.id} for {client_name}: "
            f"{len(transactions)} transactions, {job.confirmed_count} auto-confirmed"
        )

        return job

    return None


def _extract_client_name(subject, sender):
    """Extract a client name from the email subject or sender."""
    # Try to extract from subject (e.g., "Bank Statement - Neri Family Trust")
    patterns = [
        r"bank\s*statement[s]?\s*[-–—:]\s*(.+)",
        r"statement[s]?\s*[-–—:]\s*(.+)",
        r"(.+?)\s*[-–—]\s*bank\s*statement",
    ]
    for pattern in patterns:
        match = re.search(pattern, subject, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Fall back to sender email prefix
    return sender.split("@")[0].replace(".", " ").title()


# ---------------------------------------------------------------------------
# Fetch and Process All New Emails
# ---------------------------------------------------------------------------

def process_all_new_emails():
    """
    Main entry point: fetch all new bank statement emails and process them.
    Tries Microsoft Graph first, falls back to IMAP.
    Returns list of created ReviewJobs.
    """
    # Try Graph API first
    emails = fetch_emails_graph()
    if not emails:
        # Fall back to IMAP
        emails = fetch_emails_imap()

    if not emails:
        logger.info("No new bank statement emails found")
        return []

    jobs = []
    for email_data in emails:
        try:
            job = process_bank_statement_email(email_data)
            if job:
                jobs.append(job)
        except Exception as e:
            logger.error(
                f"Failed to process email from {email_data.get('sender', '?')}: {e}",
                exc_info=True,
            )

    return jobs
