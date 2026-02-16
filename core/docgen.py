"""
StatementHub — Document Generation Engine v2

Generates financial statements matching the exact format of the Access Ledger
PDF output. Supports Company, Trust, Partnership, and Sole Trader entity types.

Based on pixel-level analysis of real Firestop Victoria Pty Ltd FY2025 output.
"""
import io
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from collections import OrderedDict

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

from .models import (
    Entity, FinancialYear, TrialBalanceLine, AccountMapping,
    EntityOfficer, NoteTemplate,
)

# =============================================================================
# Constants
# =============================================================================
FONT_NAME = "Times New Roman"
FONT_SIZE_BODY = Pt(10)
FONT_SIZE_HEADING = Pt(14)
FONT_SIZE_SUBHEADING = Pt(12)
FONT_SIZE_SMALL = Pt(9)
FONT_SIZE_FOOTER = Pt(8)

FIRM_NAME = "M C & S Pty Ltd"
FIRM_ADDRESS_1 = "PO Box 4440"
FIRM_ADDRESS_2 = "Dandenong South VIC 3164"
FIRM_PHONE = "Phone: (03) 9794 0000"
FIRM_EMAIL = "Email: info@mcands.com.au"
FIRM_WEBSITE = "Website: www.mcands.com.au"


# =============================================================================
# Helpers
# =============================================================================

def _round_aud(amount):
    """Round to nearest whole dollar using standard rounding."""
    if amount is None:
        return Decimal("0")
    return Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _fmt(amount):
    """Format a Decimal as Australian currency string without $ sign.
    Rounds to whole dollars. Negatives in brackets. Zero as dash."""
    if amount is None:
        return "-"
    val = _round_aud(amount)
    if val == 0:
        return "-"
    if val < 0:
        return f"({abs(val):,.0f})"
    return f"{val:,.0f}"


def _set_run_font(run, size=FONT_SIZE_BODY, bold=False, italic=False, name=FONT_NAME):
    """Apply font formatting to a run."""
    run.font.name = name
    run.font.size = size
    run.bold = bold
    run.font.italic = italic
    # Set East Asian font
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = parse_xml(f'<w:rFonts {nsdecls("w")} w:eastAsia="{name}"/>')
        rPr.insert(0, rFonts)
    else:
        rFonts.set(qn('w:eastAsia'), name)
    return run


def _add_paragraph(doc, text="", size=FONT_SIZE_BODY, bold=False, italic=False,
                   alignment=WD_ALIGN_PARAGRAPH.LEFT, space_before=0, space_after=Pt(4),
                   first_line_indent=None):
    """Add a formatted paragraph."""
    p = doc.add_paragraph()
    p.alignment = alignment
    pf = p.paragraph_format
    pf.space_before = Pt(space_before) if isinstance(space_before, (int, float)) else space_before
    pf.space_after = space_after if isinstance(space_after, Emu) else Pt(space_after) if isinstance(space_after, (int, float)) else space_after
    if first_line_indent:
        pf.first_line_indent = first_line_indent
    if text:
        run = p.add_run(text)
        _set_run_font(run, size=size, bold=bold, italic=italic)
    return p


def _add_centered_heading(doc, text, size=FONT_SIZE_HEADING, bold=True, space_after=2):
    """Add a centered heading (entity name, ABN, report title)."""
    return _add_paragraph(doc, text, size=size, bold=bold,
                          alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=space_after)


def _add_horizontal_line(doc):
    """Add a horizontal line (thick rule)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    pPr = p._element.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:bottom w:val="single" w:sz="12" w:space="1" w:color="000000"/>'
        f'</w:pBdr>'
    )
    pPr.append(pBdr)
    return p


def _add_thin_line(doc):
    """Add a thin horizontal line."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    pPr = p._element.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:bottom w:val="single" w:sz="4" w:space="1" w:color="000000"/>'
        f'</w:pBdr>'
    )
    pPr.append(pBdr)
    return p


def _add_header_block(doc, entity, title, date_text=None):
    """Add the standard header block: entity name, ABN, title, optional date."""
    _add_centered_heading(doc, entity.entity_name, size=FONT_SIZE_HEADING, bold=True, space_after=0)
    if entity.abn:
        abn_formatted = entity.abn
        _add_centered_heading(doc, f"ABN {abn_formatted}", size=Pt(11), bold=True, space_after=0)
    _add_centered_heading(doc, title, size=FONT_SIZE_SUBHEADING, bold=True, space_after=0)
    if date_text:
        _add_centered_heading(doc, date_text, size=Pt(11), bold=True, space_after=2)
    _add_horizontal_line(doc)


def _get_period_text(fy):
    """Get 'For the year ended DD Month YYYY'."""
    return f"For the year ended {fy.end_date.strftime('%-d %B %Y')}"


def _get_as_at_text(fy):
    """Get 'as at DD Month YYYY'."""
    return f"as at {fy.end_date.strftime('%-d %B %Y')}"


def _add_statement_footer(doc, entity_type="company"):
    """Add the standard footer text for P&L and BS pages."""
    _add_horizontal_line(doc)
    text = (
        "These financial statements are unaudited. They must be read in conjunction "
        "with the attached Accountant's Compilation Report and Notes which form part "
        "of these financial statements."
    )
    _add_paragraph(doc, text, size=FONT_SIZE_FOOTER, bold=True,
                   alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)


def _add_notes_footer(doc):
    """Add the footer text for Notes pages."""
    _add_horizontal_line(doc)
    text = (
        f"These notes should be read in conjunction with the attached financial "
        f"statements and compilation report of {FIRM_NAME}."
    )
    _add_paragraph(doc, text, size=FONT_SIZE_FOOTER, bold=True,
                   alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)


def _entity_label(entity_type, plural=False):
    """Get the responsible party label for an entity type."""
    labels = {
        "company": ("the director", "the directors"),
        "trust": ("the directors of the trustee company", "the directors of the trustee company"),
        "partnership": ("the partners", "the partners"),
        "sole_trader": ("the proprietor", "the proprietor"),
    }
    pair = labels.get(entity_type, ("the director", "the directors"))
    return pair[1] if plural else pair[0]


# =============================================================================
# Trial Balance Data Extraction
# =============================================================================

def _get_tb_sections(fy):
    """
    Extract trial balance lines grouped into financial statement sections.
    Returns dict with keys: income, expenses, current_assets, noncurrent_assets,
    current_liabilities, noncurrent_liabilities, equity.
    Each value is a list of (account_code, account_name, current_balance, prior_balance) tuples.
    """
    lines = fy.trial_balance_lines.order_by("account_code").all()
    sections = {
        "income": [],
        "expenses": [],
        "current_assets": [],
        "noncurrent_assets": [],
        "current_liabilities": [],
        "noncurrent_liabilities": [],
        "equity": [],
    }

    for line in lines:
        try:
            code_num = int(line.account_code)
        except (ValueError, TypeError):
            continue

        prior = _get_prior_balance(fy, line.account_code)
        entry = (line.account_code, line.account_name, line.closing_balance, prior)

        if code_num < 1000:
            sections["income"].append(entry)
        elif code_num < 2000:
            sections["expenses"].append(entry)
        elif code_num < 2500:
            sections["current_assets"].append(entry)
        elif code_num < 3000:
            sections["noncurrent_assets"].append(entry)
        elif code_num < 3500:
            sections["current_liabilities"].append(entry)
        elif code_num < 4000:
            sections["noncurrent_liabilities"].append(entry)
        elif code_num < 5000:
            sections["equity"].append(entry)

    return sections


def _get_prior_balance(fy, account_code):
    """Get the prior year closing balance for an account code."""
    if not fy.prior_year:
        return Decimal("0")
    try:
        prior_line = fy.prior_year.trial_balance_lines.get(account_code=account_code)
        return prior_line.closing_balance
    except TrialBalanceLine.DoesNotExist:
        return Decimal("0")


def _has_prior_year(fy):
    """Check if there is prior year data."""
    if not fy.prior_year:
        return False
    return fy.prior_year.trial_balance_lines.exists()


# =============================================================================
# Financial Statement Table Helpers
# =============================================================================

def _add_amount_line(doc, label, current, prior=None, has_prior=False,
                     bold=False, indent=0, size=FONT_SIZE_BODY, note_ref="",
                     show_line_above=False, show_double_line=False, is_section_heading=False,
                     heading_size=None):
    """
    Add a single line to a financial statement using tab stops.
    This creates the two/three column layout: Label | Note | Current Year | Prior Year
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(1)
    pf.space_after = Pt(1)

    if is_section_heading:
        pf.space_before = Pt(8)
        pf.space_after = Pt(4)

    # Tab stops for alignment
    tab_stops = pf.tab_stops
    if has_prior:
        tab_stops.add_tab_stop(Cm(12), WD_ALIGN_PARAGRAPH.RIGHT)  # Note column
        tab_stops.add_tab_stop(Cm(14), WD_ALIGN_PARAGRAPH.RIGHT)  # Current year
        tab_stops.add_tab_stop(Cm(16.5), WD_ALIGN_PARAGRAPH.RIGHT)  # Prior year
    else:
        tab_stops.add_tab_stop(Cm(12), WD_ALIGN_PARAGRAPH.RIGHT)  # Note column
        tab_stops.add_tab_stop(Cm(16), WD_ALIGN_PARAGRAPH.RIGHT)  # Current year

    # Indent
    if indent > 0:
        pf.left_indent = Cm(indent * 0.5)

    # Label
    use_size = heading_size if heading_size else size
    run = p.add_run(label)
    _set_run_font(run, size=use_size, bold=bold)

    # Only add amounts for non-section-heading lines
    if not is_section_heading and current is not None:
        if note_ref:
            run = p.add_run(f"\t{note_ref}")
            _set_run_font(run, size=size)

        current_str = _fmt(current) if current is not None else ""
        run = p.add_run(f"\t{current_str}")
        _set_run_font(run, size=size, bold=bold)

        if has_prior:
            prior_str = _fmt(prior) if prior is not None else ""
            run = p.add_run(f"\t{prior_str}")
            _set_run_font(run, size=size, bold=bold)

    return p


def _add_column_headers(doc, year, has_prior=False, prior_year=None, include_note=True):
    """Add the year column headers (e.g., 'Note    2025')."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(0)

    tab_stops = pf.tab_stops
    if has_prior:
        if include_note:
            tab_stops.add_tab_stop(Cm(12), WD_ALIGN_PARAGRAPH.RIGHT)
        tab_stops.add_tab_stop(Cm(14), WD_ALIGN_PARAGRAPH.RIGHT)
        tab_stops.add_tab_stop(Cm(16.5), WD_ALIGN_PARAGRAPH.RIGHT)
    else:
        if include_note:
            tab_stops.add_tab_stop(Cm(12), WD_ALIGN_PARAGRAPH.RIGHT)
        tab_stops.add_tab_stop(Cm(16), WD_ALIGN_PARAGRAPH.RIGHT)

    if include_note:
        run = p.add_run("\tNote")
        _set_run_font(run, size=FONT_SIZE_BODY, bold=True)

    run = p.add_run(f"\t{year}")
    _set_run_font(run, size=FONT_SIZE_BODY, bold=True)

    if has_prior and prior_year:
        run = p.add_run(f"\t{prior_year}")
        _set_run_font(run, size=FONT_SIZE_BODY, bold=True)

    # Dollar sign line
    p2 = doc.add_paragraph()
    pf2 = p2.paragraph_format
    pf2.space_after = Pt(0)
    tab_stops2 = pf2.tab_stops
    if has_prior:
        tab_stops2.add_tab_stop(Cm(14), WD_ALIGN_PARAGRAPH.RIGHT)
        tab_stops2.add_tab_stop(Cm(16.5), WD_ALIGN_PARAGRAPH.RIGHT)
        run = p2.add_run(f"\t$\t$")
    else:
        tab_stops2.add_tab_stop(Cm(16), WD_ALIGN_PARAGRAPH.RIGHT)
        run = p2.add_run(f"\t$")
    _set_run_font(run, size=FONT_SIZE_BODY)

    _add_horizontal_line(doc)


# =============================================================================
# Cover Page
# =============================================================================

def _add_cover_page(doc, entity, fy):
    """Add the cover page matching the real PDF format."""
    for _ in range(8):
        doc.add_paragraph()

    _add_centered_heading(doc, entity.entity_name, size=Pt(20), bold=True, space_after=4)
    if entity.abn:
        _add_centered_heading(doc, f"ABN {entity.abn}", size=Pt(12), bold=False, space_after=12)

    _add_centered_heading(doc, "Financial Statements", size=Pt(16), bold=False, space_after=4)
    _add_centered_heading(doc, _get_period_text(fy), size=Pt(12), bold=False, space_after=40)

    # Firm details at bottom
    for _ in range(6):
        doc.add_paragraph()

    _add_centered_heading(doc, FIRM_NAME, size=Pt(10), bold=False, space_after=0)
    _add_centered_heading(doc, FIRM_ADDRESS_1, size=Pt(10), bold=False, space_after=0)
    _add_centered_heading(doc, FIRM_ADDRESS_2, size=Pt(10), bold=False, space_after=0)
    _add_centered_heading(doc, FIRM_PHONE, size=Pt(10), bold=False, space_after=0)
    _add_centered_heading(doc, FIRM_EMAIL, size=Pt(10), bold=False, space_after=0)
    _add_centered_heading(doc, FIRM_WEBSITE, size=Pt(10), bold=False, space_after=0)

    doc.add_page_break()


# =============================================================================
# Contents Page
# =============================================================================

def _add_contents_page(doc, entity, fy):
    """Add the table of contents matching the real PDF format."""
    _add_centered_heading(doc, entity.entity_name, size=FONT_SIZE_HEADING, bold=True, space_after=0)
    if entity.abn:
        _add_centered_heading(doc, f"ABN {entity.abn}", size=Pt(11), bold=True, space_after=12)

    _add_paragraph(doc, "Contents", size=FONT_SIZE_HEADING, bold=True, space_after=12)

    entity_type = entity.entity_type

    if entity_type == "company":
        items = [
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Notes to the Financial Statements",
            "Depreciation Schedule",
            "Director's Declaration",
            "Compilation Report",
        ]
    elif entity_type == "trust":
        items = [
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Notes to the Financial Statements",
            "Depreciation Schedule",
            "Trustee's Declaration",
            "Compilation Report",
        ]
    elif entity_type == "partnership":
        items = [
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Partners' Profit Distribution Summary",
            "Depreciation Schedule",
            "Partner Declaration",
            "Compilation Report",
        ]
    else:  # sole_trader
        items = [
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Notes to the Financial Statements",
            "Proprietor's Declaration",
            "Compilation Report",
        ]

    for item in items:
        p = _add_paragraph(doc, item, size=Pt(11), space_after=6)
        # Underline to look like hyperlinks
        for run in p.runs:
            run.underline = True

    doc.add_page_break()


# =============================================================================
# Detailed Profit and Loss Statement
# =============================================================================

def _add_detailed_pnl(doc, entity, fy):
    """Add the detailed P&L matching the real PDF format."""
    _add_header_block(doc, entity,
                      "Detailed Profit and Loss Statement",
                      _get_period_text(fy))

    has_prior = _has_prior_year(fy)
    year = str(fy.end_date.year)
    prior_year_str = str(fy.end_date.year - 1) if has_prior else None

    _add_column_headers(doc, year, has_prior=has_prior, prior_year=prior_year_str, include_note=False)

    sections = _get_tb_sections(fy)

    # Income section
    total_income = Decimal("0")
    total_income_prior = Decimal("0")

    _add_amount_line(doc, "Income", None, has_prior=has_prior,
                     is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

    for code, name, balance, prior in sections["income"]:
        current_val = abs(balance)  # Revenue is credit (negative), show positive
        prior_val = abs(prior) if prior else Decimal("0")
        total_income += current_val
        total_income_prior += prior_val
        _add_amount_line(doc, name, current_val, prior_val, has_prior=has_prior, indent=1)

    # Total income with line
    _add_amount_line(doc, "Total income", total_income, total_income_prior,
                     has_prior=has_prior, bold=False)

    # Blank line
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Expenses section
    total_expenses = Decimal("0")
    total_expenses_prior = Decimal("0")

    _add_amount_line(doc, "Expenses", None, has_prior=has_prior,
                     is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

    for code, name, balance, prior in sections["expenses"]:
        current_val = abs(balance)  # Expenses are debit (positive)
        prior_val = abs(prior) if prior else Decimal("0")
        total_expenses += current_val
        total_expenses_prior += prior_val
        _add_amount_line(doc, name, current_val, prior_val, has_prior=has_prior, indent=1)

    _add_amount_line(doc, "Total expenses", total_expenses, total_expenses_prior,
                     has_prior=has_prior, bold=False)

    # Blank line
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Net Profit/Loss
    net_profit = total_income - total_expenses
    net_profit_prior = total_income_prior - total_expenses_prior

    _add_amount_line(doc, "Profit (Loss) from Ordinary Activities before income tax",
                     net_profit, net_profit_prior, has_prior=has_prior, bold=True)

    _add_statement_footer(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Detailed Balance Sheet
# =============================================================================

def _add_detailed_balance_sheet(doc, entity, fy):
    """Add the detailed balance sheet matching the real PDF format."""
    _add_header_block(doc, entity,
                      f"Detailed Balance Sheet {_get_as_at_text(fy)}",
                      None)

    has_prior = _has_prior_year(fy)
    year = str(fy.end_date.year)
    prior_year_str = str(fy.end_date.year - 1) if has_prior else None

    _add_column_headers(doc, year, has_prior=has_prior, prior_year=prior_year_str, include_note=True)

    sections = _get_tb_sections(fy)

    # ---- Current Assets ----
    total_ca = Decimal("0")
    total_ca_prior = Decimal("0")

    if sections["current_assets"]:
        _add_amount_line(doc, "Current Assets", None, has_prior=has_prior,
                         is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

        # Sub-categorise current assets
        cash_items = []
        receivable_items = []
        other_ca_items = []

        for code, name, balance, prior in sections["current_assets"]:
            code_num = int(code)
            name_lower = name.lower()
            if "cash" in name_lower or "bank" in name_lower or code_num < 2100:
                cash_items.append((code, name, balance, prior))
            elif "receivable" in name_lower or "debtor" in name_lower or "trade" in name_lower:
                receivable_items.append((code, name, balance, prior))
            else:
                other_ca_items.append((code, name, balance, prior))

        # Cash Assets sub-section
        if cash_items:
            _add_amount_line(doc, "Cash Assets", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in cash_items:
                total_ca += balance
                total_ca_prior += prior
                sub_total += balance
                sub_total_prior += prior
                _add_amount_line(doc, name, balance, prior, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        # Receivables sub-section
        if receivable_items:
            _add_amount_line(doc, "Receivables", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in receivable_items:
                total_ca += balance
                total_ca_prior += prior
                sub_total += balance
                sub_total_prior += prior
                _add_amount_line(doc, name, balance, prior, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        # Other current assets
        if other_ca_items:
            _add_amount_line(doc, "Other Current Assets", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in other_ca_items:
                total_ca += balance
                total_ca_prior += prior
                sub_total += balance
                sub_total_prior += prior
                _add_amount_line(doc, name, balance, prior, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        _add_amount_line(doc, "Total Current Assets", total_ca, total_ca_prior,
                         has_prior=has_prior, bold=True)

    # ---- Non-Current Assets ----
    total_nca = Decimal("0")
    total_nca_prior = Decimal("0")

    if sections["noncurrent_assets"]:
        _add_amount_line(doc, "Non-Current Assets", None, has_prior=has_prior,
                         is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

        # PPE sub-section
        _add_amount_line(doc, "Property, Plant and Equipment", None, has_prior=has_prior,
                         bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)

        ppe_total = Decimal("0")
        ppe_total_prior = Decimal("0")
        for code, name, balance, prior in sections["noncurrent_assets"]:
            total_nca += balance
            total_nca_prior += prior
            ppe_total += balance
            ppe_total_prior += prior
            _add_amount_line(doc, name, balance, prior, has_prior=has_prior, indent=1)

        _add_amount_line(doc, "", ppe_total, ppe_total_prior, has_prior=has_prior)
        _add_amount_line(doc, "Total Non-Current Assets", total_nca, total_nca_prior,
                         has_prior=has_prior, bold=True)

    # Total Assets
    total_assets = total_ca + total_nca
    total_assets_prior = total_ca_prior + total_nca_prior
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    _add_amount_line(doc, "Total Assets", total_assets, total_assets_prior,
                     has_prior=has_prior, bold=True)

    # ---- Current Liabilities ----
    total_cl = Decimal("0")
    total_cl_prior = Decimal("0")

    if sections["current_liabilities"]:
        _add_amount_line(doc, "Current Liabilities", None, has_prior=has_prior,
                         is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

        # Sub-categorise
        tax_items = []
        trade_items = []
        other_cl_items = []

        for code, name, balance, prior in sections["current_liabilities"]:
            name_lower = name.lower()
            if "gst" in name_lower or "tax" in name_lower or "payg" in name_lower:
                tax_items.append((code, name, balance, prior))
            elif "trade" in name_lower or "creditor" in name_lower:
                trade_items.append((code, name, balance, prior))
            else:
                other_cl_items.append((code, name, balance, prior))

        if tax_items:
            _add_amount_line(doc, "Current Tax Liabilities", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in tax_items:
                val = abs(balance)  # Liabilities are credit (negative), show positive
                prior_val = abs(prior) if prior else Decimal("0")
                total_cl += val
                total_cl_prior += prior_val
                sub_total += val
                sub_total_prior += prior_val
                _add_amount_line(doc, name, val, prior_val, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        if trade_items:
            _add_amount_line(doc, "Trade and Other Payables", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in trade_items:
                val = abs(balance)
                prior_val = abs(prior) if prior else Decimal("0")
                total_cl += val
                total_cl_prior += prior_val
                sub_total += val
                sub_total_prior += prior_val
                _add_amount_line(doc, name, val, prior_val, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        if other_cl_items:
            _add_amount_line(doc, "Other Current Liabilities", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in other_cl_items:
                val = abs(balance)
                prior_val = abs(prior) if prior else Decimal("0")
                total_cl += val
                total_cl_prior += prior_val
                sub_total += val
                sub_total_prior += prior_val
                _add_amount_line(doc, name, val, prior_val, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        _add_amount_line(doc, "Total Current Liabilities", total_cl, total_cl_prior,
                         has_prior=has_prior, bold=True)

    # ---- Non-Current Liabilities ----
    total_ncl = Decimal("0")
    total_ncl_prior = Decimal("0")

    if sections["noncurrent_liabilities"]:
        _add_amount_line(doc, "Non-Current Liabilities", None, has_prior=has_prior,
                         is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

        # Sub-categorise
        loan_items = []
        other_ncl_items = []

        for code, name, balance, prior in sections["noncurrent_liabilities"]:
            name_lower = name.lower()
            if "loan" in name_lower or "borrow" in name_lower:
                loan_items.append((code, name, balance, prior))
            else:
                other_ncl_items.append((code, name, balance, prior))

        if loan_items:
            _add_amount_line(doc, "Financial Liabilities", None, has_prior=has_prior,
                             bold=True, is_section_heading=True, heading_size=FONT_SIZE_BODY)
            # Unsecured label
            p = _add_paragraph(doc, "Unsecured:", size=FONT_SIZE_BODY, bold=True, space_after=2)

            sub_total = Decimal("0")
            sub_total_prior = Decimal("0")
            for code, name, balance, prior in loan_items:
                val = abs(balance)
                prior_val = abs(prior) if prior else Decimal("0")
                total_ncl += val
                total_ncl_prior += prior_val
                sub_total += val
                sub_total_prior += prior_val
                _add_amount_line(doc, name, val, prior_val, has_prior=has_prior, indent=1)
            _add_amount_line(doc, "", sub_total, sub_total_prior, has_prior=has_prior)

        if other_ncl_items:
            for code, name, balance, prior in other_ncl_items:
                val = abs(balance)
                prior_val = abs(prior) if prior else Decimal("0")
                total_ncl += val
                total_ncl_prior += prior_val
                _add_amount_line(doc, name, val, prior_val, has_prior=has_prior, indent=1)

        _add_amount_line(doc, "Total Non-Current Liabilities", total_ncl, total_ncl_prior,
                         has_prior=has_prior, bold=True)

    # Total Liabilities
    total_liabilities = total_cl + total_ncl
    total_liabilities_prior = total_cl_prior + total_ncl_prior
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    _add_amount_line(doc, "Total Liabilities", total_liabilities, total_liabilities_prior,
                     has_prior=has_prior, bold=True)

    # Net Assets
    net_assets = total_assets - total_liabilities
    net_assets_prior = total_assets_prior - total_liabilities_prior
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    _add_amount_line(doc, "Net Assets (Liabilities)", net_assets, net_assets_prior,
                     has_prior=has_prior, bold=True)

    # ---- Equity ----
    _add_amount_line(doc, "Equity", None, has_prior=has_prior,
                     is_section_heading=True, heading_size=FONT_SIZE_SUBHEADING, bold=True)

    total_equity = Decimal("0")
    total_equity_prior = Decimal("0")

    if sections["equity"]:
        for code, name, balance, prior in sections["equity"]:
            val = abs(balance) if balance < 0 else balance  # Equity credit = positive
            prior_val = abs(prior) if prior and prior < 0 else (prior or Decimal("0"))
            total_equity += val
            total_equity_prior += prior_val
            _add_amount_line(doc, name, val, prior_val, has_prior=has_prior)
    else:
        # No equity accounts — show retained profits = net assets
        _add_amount_line(doc, "Retained profits / (accumulated losses)",
                         net_assets, net_assets_prior, has_prior=has_prior)
        total_equity = net_assets
        total_equity_prior = net_assets_prior

    _add_amount_line(doc, "Total Equity", total_equity, total_equity_prior,
                     has_prior=has_prior, bold=True)

    _add_statement_footer(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Notes to Financial Statements
# =============================================================================

def _add_notes(doc, entity, fy):
    """Add notes matching the real PDF format."""
    _add_header_block(doc, entity,
                      "Notes to the Financial Statements",
                      _get_period_text(fy))

    entity_type = entity.entity_type
    sections = _get_tb_sections(fy)

    # ---- Note 1: Summary of Significant Accounting Policies ----
    _add_paragraph(doc, "Note 1:  Summary of Significant Accounting Policies",
                   size=Pt(14), bold=True, space_after=12)

    # Basis of Preparation
    _add_paragraph(doc, "Basis of Preparation", size=FONT_SIZE_BODY, bold=True, space_after=6)

    if entity_type == "company":
        _add_paragraph(
            doc,
            f"The director has prepared the financial statements on the basis that the company "
            f"is a non-reporting entity because there are no users dependent on general purpose "
            f"financial statements. The financial statements are therefore special purpose "
            f"financial statements that have been prepared in order to meet the needs of members.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)
    elif entity_type == "trust":
        _add_paragraph(
            doc,
            f"The directors of the trustee company have prepared the financial statements on the "
            f"basis that the trust is a non-reporting entity because there are no users dependent "
            f"on general purpose financial statements. The financial statements are therefore special "
            f"purpose financial statements that have been prepared in order to meet the needs of the "
            f"trust deed and the directors of the trustee company.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)
    elif entity_type == "partnership":
        _add_paragraph(
            doc,
            f"The partners have prepared the financial statements on the basis that the partnership "
            f"is a non-reporting entity. The financial statements are therefore special purpose "
            f"financial statements that have been prepared in order to meet the needs of the partners.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)
    else:
        _add_paragraph(
            doc,
            f"The proprietor has prepared the financial statements on the basis that the business "
            f"is a non-reporting entity. The financial statements are therefore special purpose "
            f"financial statements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

    responsible = _entity_label(entity_type)
    _add_paragraph(
        doc,
        f"The financial statements have been prepared in accordance with the significant "
        f"accounting policies disclosed below, which {responsible} "
        f"{'has' if entity_type in ('company', 'sole_trader') else 'have'} determined "
        f"{'is' if entity_type in ('company', 'sole_trader') else 'are'} appropriate to meet "
        f"the needs of members. Such accounting policies are consistent with the previous period "
        f"unless stated otherwise.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

    _add_paragraph(
        doc,
        "The financial statements have been prepared on an accrual basis and are based on "
        "historical costs unless otherwise stated in the notes. The accounting policies that "
        "have been adopted in the preparation of the statements are as follows:",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)

    # Conditional accounting policies
    policy_letter = ord("a")

    # (a) Property, Plant and Equipment
    has_ppe = len(sections["noncurrent_assets"]) > 0
    if has_ppe:
        _add_paragraph(doc, f"({chr(policy_letter)})   Property, Plant and Equipment (PPE)",
                       size=FONT_SIZE_BODY, bold=True, space_after=6)
        _add_paragraph(
            doc,
            "All property, plant and equipment except for freehold land and buildings are initially "
            "measured at cost and are depreciated over their useful lives on a straight-line basis. "
            "Depreciation commences from the time the asset is available for its intended use. "
            "Leasehold improvements are depreciated over the shorter of either the unexpired period "
            "of the lease or the estimated useful lives of the improvements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
            first_line_indent=Cm(1.5))
        _add_paragraph(
            doc,
            "The carrying amount of plant and equipment is reviewed annually by the director to "
            "ensure it is not in excess of the recoverable amount from these assets. The recoverable "
            "amount is assessed on the basis of the expected net cash flows that will be received "
            "from the asset's employment and subsequent disposal. The expected net cash flows have "
            "not been discounted in determining recoverable amounts.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
            first_line_indent=Cm(1.5))
        _add_paragraph(
            doc,
            "Subsequent costs are included in the asset's carrying amount or recognised as a "
            "separate asset, as appropriate, only when it is probable that future economic benefits "
            "associated with the item will flow to the company and the cost of the item can be "
            "measured reliably. All other repairs and maintenance are recognised as expenses in "
            "profit or loss during the financial period in which they are incurred.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
            first_line_indent=Cm(1.5))
        policy_letter += 1

    # (b) Impairment of Assets
    if has_ppe:
        _add_paragraph(doc, f"({chr(policy_letter)})   Impairment of Assets",
                       size=FONT_SIZE_BODY, bold=True, space_after=6)
        _add_paragraph(
            doc,
            "At the end of each reporting period, property, plant and equipment, intangible assets "
            "and investments are reviewed to determine whether there is any indication that those "
            "assets have suffered an impairment loss. If there is an indication of possible "
            "impairment, the recoverable amount of any affected asset (or group of related assets) "
            "is estimated and compared with its carrying amount. The recoverable amount is the "
            "higher of the asset's fair value less costs of disposal and the present value of the "
            "asset's future cash flows discounted at the expected rate of return. If the estimated "
            "recoverable amount is lower, the carrying amount is reduced to the estimated "
            "recoverable amount and an impairment loss is recognised immediately in profit or loss.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
            first_line_indent=Cm(1.5))
        policy_letter += 1

    # (c) Cash and Cash Equivalents
    has_cash = len(sections["current_assets"]) > 0
    if has_cash:
        _add_paragraph(doc, f"({chr(policy_letter)})   Cash and Cash Equivalents",
                       size=FONT_SIZE_BODY, bold=True, space_after=6)
        _add_paragraph(
            doc,
            "Cash and cash equivalents include cash on hand, deposits held at call with banks, "
            "other short-term highly liquid investments with original maturities of three months "
            "or less, and bank overdrafts. Bank overdrafts are shown within borrowings in current "
            "liabilities on the balance sheet.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
            first_line_indent=Cm(1.5))
        policy_letter += 1

    # (d) Revenue and Other Income
    _add_paragraph(doc, f"({chr(policy_letter)})   Revenue and Other Income",
                   size=FONT_SIZE_BODY, bold=True, space_after=6)
    _add_paragraph(
        doc,
        "Revenue is measured at the value of the consideration received or receivable after "
        "taking into account any trade discounts and volume rebates allowed. For this purpose, "
        "deferred consideration is not discounted to present values when recognising revenue.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
        first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        "Interest revenue is recognised using the effective interest rate method, which, for "
        "floating rate financial assets, is the rate inherent in the instrument. Dividend revenue "
        "is recognised when the right to receive a dividend has been established.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
        first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        "Revenue recognised related to the provision of services is determined with reference to "
        "the stage of completion of the transaction at the end of the reporting period and where "
        "outcome of the contract can be estimated reliably. Stage of completion is determined with "
        "reference to the services performed to date as a percentage of total anticipated services "
        "to be performed. Where the outcome cannot be estimated reliably, revenue is recognised "
        "only to the extent that related expenditure is recoverable.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
        first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        "All revenue is stated net of the amount of goods and services tax (GST).",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
        first_line_indent=Cm(1.5))
    policy_letter += 1

    # (e) Leases
    _add_paragraph(doc, f"({chr(policy_letter)})   Leases",
                   size=FONT_SIZE_BODY, bold=True, space_after=6)
    entity_ref = "the company" if entity_type == "company" else "the trust" if entity_type == "trust" else "the partnership" if entity_type == "partnership" else "the business"
    _add_paragraph(
        doc, f"The {entity_ref.replace('the ', '')} as lessee",
        size=FONT_SIZE_BODY, bold=True, space_after=4, first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        f"At inception of a contract, {entity_ref} assesses if the contract contains or is a lease "
        f"under AASB 16 Leases. Where a lease exists, a right-of-use asset and a corresponding "
        f"lease liability are recognised by {entity_ref} where {entity_ref} is a lessee. However, "
        f"all contracts that are classified as short-term leases (i.e. lease with remaining lease "
        f"term of 12 months or less) and leases of low value assets will be recognised as an "
        f"operating expense on a straight-line basis over the term of the lease.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
        first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        f"{entity_ref.capitalize()} does not act as a lessor in relation to lease contracts.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
        first_line_indent=Cm(1.5))
    policy_letter += 1

    # (f) Goods and Services Tax (GST)
    _add_paragraph(doc, f"({chr(policy_letter)})   Goods and Services Tax (GST)",
                   size=FONT_SIZE_BODY, bold=True, space_after=6)
    _add_paragraph(
        doc,
        "Revenues, expenses and assets are recognised net of the amount of GST, except where the "
        "amount of GST incurred is not recoverable from the Australian Taxation Office (ATO). In "
        "these circumstances, the GST is recognised as part of the cost of acquisition of the "
        "asset or as part of an item of the expense. Receivables and payables in the balance sheet "
        "are shown inclusive of GST.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
        first_line_indent=Cm(1.5))
    _add_paragraph(
        doc,
        "Cash flows are presented in the cash flow statement on a gross basis, except for the GST "
        "components of investing and financing activities, which are disclosed as operating cash flows.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10,
        first_line_indent=Cm(1.5))
    policy_letter += 1

    _add_notes_footer(doc)
    doc.add_page_break()

    # ---- Note 2: Revenue ----
    _add_header_block(doc, entity,
                      "Notes to the Financial Statements",
                      _get_period_text(fy))

    has_prior = _has_prior_year(fy)
    year = str(fy.end_date.year)
    prior_year_str = str(fy.end_date.year - 1) if has_prior else None

    # Column header for notes
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(0)
    tab_stops = pf.tab_stops
    tab_stops.add_tab_stop(Cm(16), WD_ALIGN_PARAGRAPH.RIGHT)
    run = p.add_run(f"\t{year}")
    _set_run_font(run, size=FONT_SIZE_BODY, bold=True)
    _add_horizontal_line(doc)

    doc.add_paragraph().paragraph_format.space_after = Pt(6)

    _add_paragraph(doc, "Note 2:  Revenue", size=Pt(14), bold=True, space_after=8)
    _add_paragraph(doc, "Operating Activities:", size=FONT_SIZE_BODY, bold=True, space_after=4)
    _add_paragraph(doc, "Other operating revenue:", size=FONT_SIZE_BODY, space_after=2)

    total_revenue = Decimal("0")
    for code, name, balance, prior in sections["income"]:
        val = abs(balance)
        total_revenue += val
        _add_amount_line(doc, name, val, has_prior=False)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    _add_amount_line(doc, "", total_revenue, has_prior=False, bold=True)

    # ---- Note 3: Profit from Ordinary Activities ----
    doc.add_paragraph().paragraph_format.space_after = Pt(8)
    _add_paragraph(doc, "Note 3:  Profit from Ordinary Activities",
                   size=Pt(14), bold=True, space_after=6)
    _add_paragraph(
        doc,
        "Profit (loss) from ordinary activities before income tax has been determined after:",
        size=FONT_SIZE_BODY, space_after=8)

    _add_paragraph(doc, "Charging as Expense:", size=FONT_SIZE_BODY, bold=True, space_after=4)

    # Check for depreciation/amortisation in expenses
    depreciation_total = Decimal("0")
    amortisation_total = Decimal("0")

    for code, name, balance, prior in sections["expenses"]:
        name_lower = name.lower()
        val = abs(balance)
        if "depreciation" in name_lower:
            depreciation_total += val
        if "amortisation" in name_lower or "amortization" in name_lower:
            amortisation_total += val

    if amortisation_total > 0 or depreciation_total > 0:
        # Amortisation section
        if amortisation_total > 0:
            _add_paragraph(doc, "Amortisation of non-current assets:", size=FONT_SIZE_BODY, space_after=2)
            _add_amount_line(doc, " - Leased assets", amortisation_total, has_prior=False, indent=1)
            _add_amount_line(doc, "Total amortisation expenses", amortisation_total, has_prior=False)

        # Depreciation section
        if depreciation_total > 0:
            _add_paragraph(doc, "Depreciation of non-current assets:", size=FONT_SIZE_BODY, space_after=2)
            _add_amount_line(doc, " - Other", depreciation_total, has_prior=False, indent=1)
            _add_amount_line(doc, "Total depreciation expenses", depreciation_total, has_prior=False)

    _add_notes_footer(doc)
    doc.add_page_break()


# =============================================================================
# Director's / Trustee's / Partner Declaration
# =============================================================================

def _add_declaration(doc, entity, fy):
    """Add the declaration page matching the real PDF format."""
    entity_type = entity.entity_type
    signatories = entity.officers.filter(
        is_signatory=True,
        date_ceased__isnull=True,
    ).order_by("display_order")

    num_signatories = signatories.count()
    # Determine singular/plural for directors
    singular = num_signatories <= 1

    if entity_type == "company":
        title = "Director's Declaration" if singular else "Directors' Declaration"
        _add_header_block(doc, entity, title, None)

        director_word = "director" if singular else "directors"
        has_have = "has" if singular else "have"

        _add_paragraph(
            doc,
            f"The {director_word} {has_have} determined that the company is not a reporting entity "
            f"and that this special purpose financial report should be prepared in accordance with "
            f"the accounting policies prescribed in Note 1 to the financial statements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)

        _add_paragraph(
            doc,
            f"The {director_word} of the company declare{'s' if singular else ''} that:",
            size=FONT_SIZE_BODY, space_after=6)

        _add_paragraph(
            doc,
            f"1.  the financial statements and notes, present fairly the company's financial "
            f"position as at {fy.end_date.strftime('%-d %B %Y')} and its performance for the year "
            f"ended on that date in accordance with the accounting policies described in Note 1 "
            f"to the financial statements;",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6,
            first_line_indent=Cm(0))

        _add_paragraph(
            doc,
            f"2.  in the {director_word}'s opinion, there are reasonable grounds to believe that "
            f"the company will be able to pay its debts as and when they become due and payable.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=12,
            first_line_indent=Cm(0))

        _add_paragraph(
            doc,
            f"This declaration is made in accordance with a resolution of the {director_word}.",
            size=FONT_SIZE_BODY, space_after=20)

    elif entity_type == "trust":
        _add_header_block(doc, entity, "Trustee's Declaration", None)

        _add_paragraph(
            doc,
            f"The directors of the trustee company have determined that the trust is not a reporting "
            f"entity and that this special purpose financial report should be prepared in accordance "
            f"with the accounting policies prescribed in Note 1 to the financial statements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)

        _add_paragraph(
            doc,
            "The directors of the trustee company declare that:",
            size=FONT_SIZE_BODY, space_after=6)

        _add_paragraph(
            doc,
            f"1.  the financial statements and notes, present fairly the trust's financial "
            f"position as at {fy.end_date.strftime('%-d %B %Y')} and its performance for the year "
            f"ended on that date in accordance with the accounting policies described in Note 1 "
            f"to the financial statements;",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

        _add_paragraph(
            doc,
            f"2.  in the directors' opinion, there are reasonable grounds to believe that the "
            f"trust will be able to pay its debts as and when they become due and payable.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=12)

        _add_paragraph(
            doc,
            "This declaration is made in accordance with a resolution of the directors of the "
            "trustee company.",
            size=FONT_SIZE_BODY, space_after=20)

    elif entity_type == "partnership":
        _add_header_block(doc, entity, "Partner Declaration", None)

        _add_paragraph(
            doc,
            "The partners have determined that the partnership is not a reporting entity and that "
            "this special purpose financial report should be prepared in accordance with the "
            "accounting policies described in the financial statements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)

        _add_paragraph(doc, "The partners declare that:", size=FONT_SIZE_BODY, space_after=6)

        _add_paragraph(
            doc,
            f"(a) the financial statements comply with the accounting policies described therein; and",
            size=FONT_SIZE_BODY, space_after=6)

        _add_paragraph(
            doc,
            f"(b) the financial statements present fairly the partnership's financial position as at "
            f"{fy.end_date.strftime('%-d %B %Y')} and its performance for the year ended on that date.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

        _add_paragraph(
            doc,
            "In the partners' opinion, there are reasonable grounds to believe that the partnership "
            "will be able to pay its debts as and when they become due and payable.",
            size=FONT_SIZE_BODY, space_after=20)

    else:  # sole_trader
        _add_header_block(doc, entity, "Proprietor's Declaration", None)

        _add_paragraph(
            doc,
            "The proprietor has determined that this special purpose financial statement should be "
            "prepared in accordance with the accounting policies described in the financial statements.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8)

        _add_paragraph(
            doc,
            f"The proprietor declares that the financial statements present fairly the business's "
            f"financial position as at {fy.end_date.strftime('%-d %B %Y')} and its performance for "
            f"the year ended on that date.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=20)

    # Signature blocks
    for officer in signatories:
        doc.add_paragraph().paragraph_format.space_after = Pt(20)
        _add_paragraph(doc, "_" * 50, size=FONT_SIZE_BODY, space_after=0)
        _add_paragraph(doc, officer.full_name, size=FONT_SIZE_BODY, space_after=0)
        if entity_type == "company":
            _add_paragraph(doc, "Director", size=FONT_SIZE_BODY, space_after=6)
        elif entity_type == "trust":
            _add_paragraph(doc, "Director of the Trustee Company", size=FONT_SIZE_BODY, space_after=6)
        elif entity_type == "partnership":
            _add_paragraph(doc, "Partner", size=FONT_SIZE_BODY, space_after=6)
        else:
            _add_paragraph(doc, "Proprietor", size=FONT_SIZE_BODY, space_after=6)

    _add_paragraph(doc, "Dated:", size=FONT_SIZE_BODY, space_after=2)

    doc.add_page_break()


# =============================================================================
# Compilation Report
# =============================================================================

def _add_compilation_report(doc, entity, fy):
    """Add the compilation report matching the real PDF format (APES 315)."""
    _add_header_block(doc, entity,
                      f"Compilation Report to {entity.entity_name}",
                      None)

    entity_type = entity.entity_type
    end_date_str = fy.end_date.strftime('%-d %B %Y')

    # Opening paragraph
    _add_paragraph(
        doc,
        f"We have compiled the accompanying special purpose financial statements of "
        f"{entity.entity_name}, which comprise the balance sheet as at {end_date_str}, "
        f"the Statement of Profit and Loss for the year then ended, a summary of significant "
        f"accounting policies and other explanatory notes. The specific purpose for which the "
        f"special purpose financial statements have been prepared is set out in Note 1 to the "
        f"financial statements.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)

    # The Responsibility of the Director/Trustee/Partner
    responsible = _entity_label(entity_type)
    responsible_title = responsible.replace("the ", "").title()

    p = _add_paragraph(doc, f"The Responsibility of {responsible_title}",
                       size=FONT_SIZE_BODY, bold=False, italic=True, space_after=4)

    if entity_type == "company":
        _add_paragraph(
            doc,
            f"The director of {entity.entity_name} is solely responsible for the information "
            f"contained in the special purpose financial statements, the reliability, accuracy "
            f"and completeness of the information and for the determination that the significant "
            f"accounting policies used are appropriate to meet the needs and for the purpose that "
            f"the financial statements were prepared.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)
    elif entity_type == "trust":
        _add_paragraph(
            doc,
            f"The directors of the trustee company are solely responsible for the information "
            f"contained in the special purpose financial statements, the reliability, accuracy "
            f"and completeness of the information and for the determination that the significant "
            f"accounting policies used are appropriate to meet the needs of the trust deed and "
            f"the directors of the trustee company.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)
    elif entity_type == "partnership":
        _add_paragraph(
            doc,
            f"The partners are solely responsible for the information contained in the special "
            f"purpose financial statements, the reliability, accuracy and completeness of the "
            f"information and for the determination that the significant accounting policies used "
            f"are appropriate to meet the needs and for the purpose that the financial statements "
            f"were prepared.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)
    else:
        _add_paragraph(
            doc,
            f"The proprietor is solely responsible for the information contained in the special "
            f"purpose financial statements, the reliability, accuracy and completeness of the "
            f"information and for the determination that the significant accounting policies used "
            f"are appropriate.",
            size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)

    # Our Responsibility
    _add_paragraph(doc, "Our Responsibility",
                   size=FONT_SIZE_BODY, italic=True, space_after=4)

    _add_paragraph(
        doc,
        f"On the basis of information provided by {responsible}, we have compiled the "
        f"accompanying special purpose financial statements in accordance with the significant "
        f"accounting policies as described in Note 1 to the financial statements and APES 315 "
        f"Compilation of Financial Information.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

    _add_paragraph(
        doc,
        "We have applied our expertise in accounting and financial reporting to compile these "
        "financial statements in accordance with the significant accounting policies described "
        "in Note 1 to the financial statements. We have complied with the relevant ethical "
        "requirements of APES 110 Code of Ethics for Professional Accountants (including "
        "Independence Standards).",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=10)

    # Assurance Disclaimer
    _add_paragraph(doc, "Assurance Disclaimer",
                   size=FONT_SIZE_BODY, italic=True, space_after=4)

    _add_paragraph(
        doc,
        "Since a compilation engagement is not an assurance engagement, we are not required to "
        "verify the reliability, accuracy or completeness of the information provided to us by "
        "management to compile these financial statements. Accordingly, we do not express an "
        "audit opinion or a review conclusion on these financial statements.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)

    _add_paragraph(
        doc,
        f"The special purpose financial statements were compiled exclusively for the benefit of "
        f"{responsible} who is responsible for the reliability, accuracy and completeness of the "
        f"information used to compile them. Accordingly, these special purpose financial statements "
        f"may not be suitable for other purposes. We do not accept responsibility for the contents "
        f"of the special purpose financial statements.",
        size=FONT_SIZE_BODY, alignment=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=20)

    # Signature block
    doc.add_paragraph().paragraph_format.space_after = Pt(20)
    _add_paragraph(doc, "_" * 40, size=FONT_SIZE_BODY, space_after=0)
    _add_paragraph(doc, FIRM_NAME, size=FONT_SIZE_BODY, space_after=0)
    _add_paragraph(doc, FIRM_ADDRESS_1, size=FONT_SIZE_BODY, space_after=0)
    _add_paragraph(doc, FIRM_ADDRESS_2, size=FONT_SIZE_BODY, space_after=6)
    _add_paragraph(doc, f"{date.today().strftime('%-d %B, %Y')}", size=FONT_SIZE_BODY, space_after=2)


# =============================================================================
# Partners' Profit Distribution Summary
# =============================================================================

def _add_partners_distribution(doc, entity, fy):
    """Add the partners' profit distribution summary (partnership only)."""
    _add_header_block(doc, entity,
                      "Partners' Profit Distribution Summary",
                      _get_period_text(fy))

    sections = _get_tb_sections(fy)
    total_income = sum(abs(b) for _, _, b, _ in sections["income"])
    total_expenses = sum(abs(b) for _, _, b, _ in sections["expenses"])
    net_profit = total_income - total_expenses

    partners = entity.officers.filter(
        role=EntityOfficer.OfficerRole.PARTNER,
        date_ceased__isnull=True,
    ).order_by("display_order")

    has_prior = _has_prior_year(fy)
    year = str(fy.end_date.year)

    _add_column_headers(doc, year, has_prior=False, include_note=False)

    _add_paragraph(doc, "Partners' Share of Profit", size=FONT_SIZE_BODY, bold=True, space_after=6)

    for partner in partners:
        share_pct = partner.profit_share_percentage or Decimal("0")
        share_amount = net_profit * share_pct / Decimal("100") if share_pct else Decimal("0")
        _add_amount_line(doc, f"{partner.full_name} ({share_pct}%)",
                         share_amount, has_prior=False, indent=1)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    _add_amount_line(doc, "Total Profit Distributed", net_profit, has_prior=False, bold=True)

    _add_statement_footer(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Main Generation Function
# =============================================================================

def generate_financial_statements(financial_year_id) -> io.BytesIO:
    """
    Generate a complete set of financial statements for a financial year.
    Returns a BytesIO object containing the Word document.

    Document order matches the real Access Ledger PDF output:
    1. Cover Page
    2. Contents
    3. Detailed P&L
    4. Detailed Balance Sheet
    5. Notes to Financial Statements
    6. Declaration
    7. Compilation Report
    """
    fy = FinancialYear.objects.select_related(
        "entity", "entity__client", "prior_year"
    ).get(pk=financial_year_id)

    entity = fy.entity
    entity_type = entity.entity_type

    doc = Document()

    # Set default font to Times New Roman
    style = doc.styles["Normal"]
    font = style.font
    font.name = FONT_NAME
    font.size = FONT_SIZE_BODY

    # Set margins
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(2.54)
        section.right_margin = Cm(2.54)

    # =========================================================================
    # Build document in the correct order (matching real PDF)
    # =========================================================================

    # 1. Cover Page
    _add_cover_page(doc, entity, fy)

    # 2. Contents Page
    _add_contents_page(doc, entity, fy)

    # 3. Detailed Profit and Loss Statement
    _add_detailed_pnl(doc, entity, fy)

    # 4. Detailed Balance Sheet
    _add_detailed_balance_sheet(doc, entity, fy)

    # 5. Notes to Financial Statements (company and trust)
    if entity_type in ("company", "trust", "sole_trader"):
        _add_notes(doc, entity, fy)

    # 6. Partners' Distribution (partnership only)
    if entity_type == "partnership":
        _add_partners_distribution(doc, entity, fy)

    # 7. Declaration
    _add_declaration(doc, entity, fy)

    # 8. Compilation Report (always last)
    _add_compilation_report(doc, entity, fy)

    # Save to BytesIO
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer
