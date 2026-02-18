"""
Bank statement PDF parsers using pdfplumber for direct text extraction.

Each bank has its own parser function. The main entry point is
`extract_transactions_from_pdf_direct()` which auto-detects the bank
and delegates to the appropriate parser.

This replaces the Claude-based extraction for near-instant processing.
"""
import io
import re
import logging
from decimal import Decimal

import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CBA (Commonwealth Bank of Australia) Parser
# ---------------------------------------------------------------------------

# Regex patterns for CBA statements
# Date at start of line: "DD Mon" (e.g., "31 Jul", "01 Aug")
CBA_DATE_RE = re.compile(r"^(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))\s+(.+)")

# Opening balance line: "DD Mon YYYY OPENING BALANCE $XX,XXX.XX CR"
CBA_OPENING_RE = re.compile(
    r"^(\d{1,2}\s+\w+)\s+\d{4}\s+OPENING\s+BALANCE\s+\$([\d,]+\.\d{2})\s*(?:CR|DR)?$"
)

# Closing balance line: "DD Mon YYYY CLOSING BALANCE $XX,XXX.XX CR"
CBA_CLOSING_RE = re.compile(
    r"^(\d{1,2}\s+\w+)\s+\d{4}\s+CLOSING\s+BALANCE\s+\$([\d,]+\.\d{2})\s*(?:CR|DR)?$"
)

# Transaction line with DEBIT amount: description ... amount $ $balanceCR
# The "$ " before the balance is the CBA marker for debits
CBA_DEBIT_RE = re.compile(
    r"^(.*?)\s+([\d,]+\.\d{2})\s+\$\s+\$([\d,]+\.\d{2})\s*(?:CR|DR)?$"
)

# Transaction line with CREDIT amount: description ... $amount $balanceCR
CBA_CREDIT_RE = re.compile(
    r"^(.*?)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})\s*(?:CR|DR)?$"
)

# Balance-only line (for opening/closing): $XX,XXX.XX CR
CBA_BALANCE_ONLY_RE = re.compile(
    r"\$([\d,]+\.\d{2})\s*(?:CR|DR)?$"
)

# Month abbreviation to number mapping
MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _parse_cba_amount(amount_str):
    """Parse a CBA amount string like '9,109.45' to Decimal."""
    return Decimal(amount_str.replace(",", ""))


def _cba_date_to_iso(date_str, year):
    """Convert 'DD Mon' to 'YYYY-MM-DD'."""
    parts = date_str.strip().split()
    if len(parts) != 2:
        return ""
    day = parts[0].zfill(2)
    month = MONTH_MAP.get(parts[1], "01")
    return f"{year}-{month}-{day}"


def _detect_year_from_period(period_str):
    """Extract year from period string like '31 Jul 2025 - 30 Oct 2025'."""
    match = re.search(r"(\d{4})", period_str)
    return match.group(1) if match else "2025"


def parse_cba_statement(pdf_content):
    """
    Parse a CBA bank statement PDF.

    Args:
        pdf_content: bytes of the PDF file

    Returns:
        dict with keys:
            opening_balance, closing_balance, account_name, bsb,
            account_number, period_start, period_end, transactions
    """
    result = {
        "opening_balance": 0,
        "closing_balance": 0,
        "account_name": "",
        "bsb": "",
        "account_number": "",
        "period_start": "",
        "period_end": "",
        "transactions": [],
    }

    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        all_lines = []
        header_parsed = False
        year = "2025"

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")

            # Parse header info from page 1
            if not header_parsed:
                for line in lines:
                    # Account number (BSB + Account)
                    acct_match = re.search(r"Account\s+Number\s+(\d{2}\s*\d{4})\s+(\d+)", line)
                    if acct_match:
                        result["bsb"] = acct_match.group(1).replace(" ", "-")
                        # Fix BSB format: "06 2692" -> "062-692"
                        bsb_raw = acct_match.group(1).replace(" ", "")
                        if len(bsb_raw) == 6:
                            result["bsb"] = f"{bsb_raw[:3]}-{bsb_raw[3:]}"
                        else:
                            result["bsb"] = bsb_raw
                        result["account_number"] = acct_match.group(2)

                    # Statement period
                    period_match = re.search(
                        r"Period\s+(\d{1,2}\s+\w+\s+\d{4})\s*-\s*(\d{1,2}\s+\w+\s+\d{4})", line
                    )
                    if period_match:
                        result["period_start"] = period_match.group(1)
                        result["period_end"] = period_match.group(2)
                        year = _detect_year_from_period(line)

                    # Closing balance from header
                    cb_match = re.search(r"Closing\s+Balance\s+\$([\d,]+\.\d{2})\s*(?:CR|DR)?", line)
                    if cb_match:
                        result["closing_balance"] = float(_parse_cba_amount(cb_match.group(1)))

                    # Account name
                    name_match = re.search(r"Name:\s+(.+)", line)
                    if name_match:
                        result["account_name"] = name_match.group(1).strip()

                header_parsed = True

            # Collect all transaction lines (skip header/footer lines)
            in_transactions = False
            for line in lines:
                # Start of transaction table
                if re.match(r"Date\s+Transaction\s+Debit\s+Credit\s+Balance", line):
                    in_transactions = True
                    continue

                # End markers
                if re.match(r"Opening\s+balance\s+-\s+Total\s+debits", line):
                    in_transactions = False
                    continue
                if re.match(r"\$[\d,]+\.\d{2}\s+CR\s+\$[\d,]+\.\d{2}", line):
                    in_transactions = False
                    continue

                if in_transactions:
                    all_lines.append(line.strip())

        # Now parse the collected transaction lines.
        # Key insight: CBA multi-line transactions have the format:
        #   DD Mon Description first line
        #   continuation with amount $X.XX $balanceCR
        # The continuation line may start with a date reference (e.g., "01 Sep PaedsPpl")
        # which looks like a new transaction date but is actually part of the previous one.
        # Rule: a date-prefixed line is only a NEW transaction if there is no current
        # transaction waiting for an amount, OR if the line itself has an amount.
        transactions = []
        current_txn = None

        def _try_parse_amount(text):
            """Try to extract debit or credit amount from a line.
            Returns (amount_float, desc_part) or None."""
            dm = CBA_DEBIT_RE.match(text)
            if dm:
                return -float(_parse_cba_amount(dm.group(2))), dm.group(1).strip()
            cm = CBA_CREDIT_RE.match(text)
            if cm:
                return float(_parse_cba_amount(cm.group(2))), cm.group(1).strip()
            return None

        for line in all_lines:
            if not line:
                continue

            # Check for OPENING BALANCE
            ob_match = CBA_OPENING_RE.match(line)
            if ob_match:
                result["opening_balance"] = float(_parse_cba_amount(ob_match.group(2)))
                continue

            # Check for CLOSING BALANCE
            cb_match = CBA_CLOSING_RE.match(line)
            if cb_match:
                result["closing_balance"] = float(_parse_cba_amount(cb_match.group(2)))
                continue

            date_match = CBA_DATE_RE.match(line)

            if date_match:
                date_str = date_match.group(1)
                rest = date_match.group(2)
                amount_result = _try_parse_amount(rest)

                if amount_result is not None:
                    # Line has a date AND an amount
                    amount, desc = amount_result

                    if current_txn and current_txn["amount"] == 0:
                        # Current txn is waiting for an amount — this line
                        # is a continuation (e.g., "01 Sep PaedsPpl $600.00 ...")
                        if desc:
                            current_txn["description"] += " " + desc
                        current_txn["amount"] = amount
                        transactions.append(current_txn)
                        current_txn = None
                    else:
                        # No pending txn or pending txn already has amount
                        # — this is a complete single-line transaction
                        if current_txn:
                            transactions.append(current_txn)
                        current_txn = {
                            "date": _cba_date_to_iso(date_str, year),
                            "description": desc,
                            "amount": amount,
                        }
                        transactions.append(current_txn)
                        current_txn = None
                else:
                    # Date line with no amount — start of a new multi-line txn
                    if current_txn:
                        # Save previous (might have amount=0 if malformed)
                        if current_txn["amount"] != 0:
                            transactions.append(current_txn)
                        else:
                            logger.warning(
                                f"Dropping zero-amount txn: {current_txn['description'][:60]}"
                            )
                    current_txn = {
                        "date": _cba_date_to_iso(date_str, year),
                        "description": rest.strip(),
                        "amount": 0,
                    }
            else:
                # Continuation line (no date prefix)
                if current_txn:
                    amount_result = _try_parse_amount(line)
                    if amount_result is not None:
                        amount, desc_part = amount_result
                        if desc_part:
                            current_txn["description"] += " " + desc_part
                        current_txn["amount"] = amount
                        transactions.append(current_txn)
                        current_txn = None
                    else:
                        # Pure description continuation
                        current_txn["description"] += " " + line.strip()

        # Don't forget the last transaction
        if current_txn and current_txn["amount"] != 0:
            transactions.append(current_txn)

    # Determine year for dates that might span year boundary
    # (e.g., statement period Jul-Oct means all dates are same year)
    # For statements spanning Dec-Jan, we'd need to handle year rollover
    # but for now, use the year from the period

    result["transactions"] = transactions
    logger.info(
        f"CBA parser: {len(transactions)} transactions, "
        f"opening={result['opening_balance']}, closing={result['closing_balance']}"
    )
    return result


# ---------------------------------------------------------------------------
# Bank Detection & Main Entry Point
# ---------------------------------------------------------------------------

def detect_bank(pdf_content):
    """Detect which bank a PDF statement is from."""
    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        if not pdf.pages:
            return "unknown"
        text = pdf.pages[0].extract_text() or ""
        text_lower = text.lower()

        if "commonwealth bank" in text_lower or "commbank" in text_lower:
            return "cba"
        elif "westpac" in text_lower:
            return "westpac"
        elif "national australia bank" in text_lower or "nab" in text_lower:
            return "nab"
        elif "anz" in text_lower:
            return "anz"
        else:
            return "unknown"


def extract_transactions_from_pdf_direct(pdf_content, filename=""):
    """
    Main entry point: extract transactions from a bank statement PDF
    using direct text extraction (no AI).

    Args:
        pdf_content: bytes of the PDF file
        filename: original filename (for logging)

    Returns:
        dict with keys: opening_balance, closing_balance, account_name,
        bsb, account_number, period_start, period_end, transactions

    Raises:
        ValueError if bank is not supported
    """
    bank = detect_bank(pdf_content)
    logger.info(f"Detected bank: {bank} for file: {filename}")

    if bank == "cba":
        return parse_cba_statement(pdf_content)
    else:
        raise ValueError(
            f"Unsupported bank format for '{filename}'. "
            f"Detected: {bank}. Currently supported: CBA. "
            f"Please contact support to add your bank."
        )
