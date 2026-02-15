"""
StatementHub — Document Generation Engine

Generates Word (.docx) financial statements for all entity types:
- Company (Special Purpose)
- Trust (Special Purpose)
- Partnership (Special Purpose)
- Sole Trader (Special Purpose)

Based on the Access Ledger template analysis.
"""
import io
from decimal import Decimal
from datetime import date
from collections import OrderedDict

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT

from .models import (
    Entity, FinancialYear, TrialBalanceLine, AccountMapping,
    EntityOfficer, NoteTemplate,
)


# =============================================================================
# Helpers
# =============================================================================

def _fmt(amount):
    """Format a Decimal as Australian currency string without $ sign."""
    if amount is None:
        return "-"
    val = Decimal(str(amount))
    if val == 0:
        return "-"
    if val < 0:
        return f"({abs(val):,.0f})"
    return f"{val:,.0f}"


def _set_cell_text(cell, text, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT, size=9):
    """Set cell text with formatting."""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    run = p.add_run(str(text))
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Arial"
    return run


def _add_heading_paragraph(doc, text, size=14, bold=True, alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=6):
    """Add a formatted heading paragraph."""
    p = doc.add_paragraph()
    p.alignment = alignment
    p.space_after = Pt(space_after)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Arial"
    return p


def _add_body_paragraph(doc, text, size=9, bold=False, alignment=WD_ALIGN_PARAGRAPH.LEFT, space_after=4):
    """Add a formatted body paragraph."""
    p = doc.add_paragraph()
    p.alignment = alignment
    p.space_after = Pt(space_after)
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "Arial"
    return p


def _add_footer_text(doc, entity_type):
    """Add the standard footer text."""
    if entity_type == "company":
        text = "The accompanying notes form part of these financial statements."
    else:
        text = ("These financial statements are unaudited. They must be read in conjunction "
                "with the attached Accountant's Compilation Report and Notes which form part "
                "of these financial statements.")
    _add_body_paragraph(doc, text, size=7, alignment=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)


def _get_period_text(fy):
    """Get the period description text."""
    return f"For the year ended {fy.end_date.strftime('%d %B %Y')}"


def _get_as_at_text(fy):
    """Get the 'as at' date text."""
    return f"As at {fy.end_date.strftime('%d %B %Y')}"


def _aggregate_trial_balance(fy):
    """
    Aggregate trial balance lines by their mapped line item.
    Returns a dict: { AccountMapping.standard_code: { 'label': str, 'current': Decimal, 'prior': Decimal } }
    """
    lines = fy.trial_balance_lines.select_related("mapped_line_item").all()
    aggregated = {}

    for line in lines:
        if not line.mapped_line_item:
            continue
        code = line.mapped_line_item.standard_code
        if code not in aggregated:
            aggregated[code] = {
                "label": line.mapped_line_item.line_item_label,
                "section": line.mapped_line_item.statement_section,
                "statement": line.mapped_line_item.financial_statement,
                "display_order": line.mapped_line_item.display_order,
                "current": Decimal("0"),
                "prior": Decimal("0"),
            }
        aggregated[code]["current"] += line.closing_balance

    # Get prior year data if available
    if fy.prior_year:
        prior_lines = fy.prior_year.trial_balance_lines.select_related("mapped_line_item").all()
        for line in prior_lines:
            if not line.mapped_line_item:
                continue
            code = line.mapped_line_item.standard_code
            if code not in aggregated:
                aggregated[code] = {
                    "label": line.mapped_line_item.line_item_label,
                    "section": line.mapped_line_item.statement_section,
                    "statement": line.mapped_line_item.financial_statement,
                    "display_order": line.mapped_line_item.display_order,
                    "current": Decimal("0"),
                    "prior": Decimal("0"),
                }
            aggregated[code]["prior"] += line.closing_balance

    return aggregated


def _get_detailed_lines(fy):
    """Get all trial balance lines grouped by section for detailed statements."""
    lines = fy.trial_balance_lines.select_related("mapped_line_item").order_by("account_code")
    grouped = OrderedDict()

    for line in lines:
        if line.mapped_line_item:
            section = line.mapped_line_item.statement_section
        else:
            # Determine section from account code
            try:
                code_num = int(line.account_code)
                if code_num < 1000:
                    section = "Revenue"
                elif code_num < 2000:
                    section = "Expenses"
                elif code_num < 3000:
                    section = "Assets"
                elif code_num < 4000:
                    section = "Liabilities"
                elif code_num < 4200:
                    section = "Equity"
                else:
                    section = "Other"
            except ValueError:
                section = "Other"

        if section not in grouped:
            grouped[section] = []
        grouped[section].append(line)

    return grouped


def _get_prior_balance(fy, account_code):
    """Get the prior year closing balance for an account code."""
    if not fy.prior_year:
        return Decimal("0")
    try:
        prior_line = fy.prior_year.trial_balance_lines.get(account_code=account_code)
        return prior_line.closing_balance
    except TrialBalanceLine.DoesNotExist:
        return Decimal("0")


# =============================================================================
# Financial Statement Table Builder
# =============================================================================

def _add_statement_table(doc, headers, rows, col_widths=None):
    """
    Add a formatted financial statement table.
    headers: list of strings
    rows: list of dicts with 'cells' (list of strings), 'bold' (bool), 'is_total' (bool)
    """
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    # Header row
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        _set_cell_text(cell, header, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=9)
        # Bottom border for header
        tc = cell._element
        tcPr = tc.get_or_add_tcPr()

    # Data rows
    for row_idx, row_data in enumerate(rows):
        row = table.rows[row_idx + 1]
        cells = row_data.get("cells", [])
        is_bold = row_data.get("bold", False)
        is_total = row_data.get("is_total", False)
        indent = row_data.get("indent", 0)

        for col_idx, cell_text in enumerate(cells):
            cell = row.cells[col_idx]
            if col_idx == 0:
                # Label column — left aligned
                prefix = "  " * indent
                _set_cell_text(cell, prefix + str(cell_text), bold=is_bold,
                               align=WD_ALIGN_PARAGRAPH.LEFT, size=9)
            else:
                # Amount columns — right aligned
                _set_cell_text(cell, str(cell_text), bold=is_bold,
                               align=WD_ALIGN_PARAGRAPH.RIGHT, size=9)

    return table


# =============================================================================
# Cover Page
# =============================================================================

def _add_cover_page(doc, entity, fy):
    """Add the cover page."""
    # Add some spacing
    for _ in range(6):
        doc.add_paragraph()

    _add_heading_paragraph(doc, entity.entity_name, size=18, bold=True)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=12, bold=False, space_after=20)

    _add_heading_paragraph(doc, "Financial Statements", size=14, bold=True, space_after=10)
    _add_heading_paragraph(doc, _get_period_text(fy), size=12, bold=False, space_after=40)

    # Firm details
    _add_heading_paragraph(doc, "M C & S Pty Ltd", size=10, bold=True, space_after=2)
    _add_heading_paragraph(doc, "PO Box 4440", size=9, bold=False, space_after=2)
    _add_heading_paragraph(doc, "Dandenong South VIC 3164", size=9, bold=False, space_after=2)
    _add_heading_paragraph(doc, "Phone: (03) 9794 8012", size=9, bold=False, space_after=2)
    _add_heading_paragraph(doc, "Email: admin@mcsaccountants.com.au", size=9, bold=False, space_after=2)

    doc.add_page_break()


# =============================================================================
# Contents Page
# =============================================================================

def _add_contents_page(doc, entity, fy):
    """Add the table of contents page."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=10)
    _add_heading_paragraph(doc, "Contents", size=14, bold=True, space_after=20)

    entity_type = entity.entity_type

    if entity_type == "company":
        items = [
            "Compilation Report",
            "Trading Account",
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Profit and Loss Statement",
            "Notes to the Financial Statements",
            "Director's Declaration",
        ]
    elif entity_type == "trust":
        items = [
            "Trading Account",
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
            "Compilation Report",
            "Partner Declaration",
        ]
    else:  # sole_trader
        items = [
            "Detailed Profit and Loss Statement",
            "Detailed Balance Sheet",
            "Compilation Report",
            "Proprietor's Declaration",
        ]

    for i, item in enumerate(items, 1):
        _add_body_paragraph(doc, f"{i}.  {item}", size=11, space_after=8)

    doc.add_page_break()


# =============================================================================
# Compilation Report
# =============================================================================

def _add_compilation_report(doc, entity, fy):
    """Add the compilation report (APES 315)."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=10)

    entity_type = entity.entity_type

    if entity_type == "company":
        title = f"Compilation Report to {entity.entity_name}"
        responsible_party = "the Director"
        responsible_text = (
            f"The director of {entity.entity_name} is solely responsible for the information "
            f"contained in the special purpose financial statements and has determined that the "
            f"accounting policies used are consistent and are appropriate to satisfy the requirements "
            f"of the director."
        )
    elif entity_type == "trust":
        title = f"Compilation Report to {entity.entity_name}"
        responsible_party = "the Directors of the Trustee Company"
        responsible_text = (
            f"The directors of the trustee company are solely responsible for the information "
            f"contained in the special purpose financial statements and have determined that the "
            f"accounting policies used are consistent and are appropriate to satisfy the requirements "
            f"of the trust deed and the directors of the trustee company."
        )
    elif entity_type == "partnership":
        title = f"Compilation Report to {entity.entity_name}"
        responsible_party = "the Partners"
        responsible_text = (
            f"The partners are solely responsible for the information contained in the special "
            f"purpose financial statements and have determined that the accounting policies used "
            f"are consistent and are appropriate to satisfy the requirements of the partners."
        )
    else:
        title = f"Compilation Report to {entity.entity_name}"
        responsible_party = "the Proprietor"
        responsible_text = (
            f"The proprietor is solely responsible for the information contained in the special "
            f"purpose financial statements and has determined that the accounting policies used "
            f"are consistent and are appropriate to satisfy the requirements of the proprietor."
        )

    _add_heading_paragraph(doc, title, size=12, bold=True, space_after=15)

    # Responsibility section
    _add_body_paragraph(doc, f"The Responsibility of {responsible_party}", size=10, bold=True, space_after=6)
    _add_body_paragraph(doc, responsible_text, size=9, space_after=10)

    # Our Responsibility
    _add_body_paragraph(doc, "Our Responsibility", size=10, bold=True, space_after=6)
    _add_body_paragraph(
        doc,
        f"On the basis of the information provided by {responsible_party.lower()}, we have compiled the "
        f"accompanying special purpose financial statements of {entity.entity_name} for the "
        f"year ended {fy.end_date.strftime('%d %B %Y')} in accordance with APES 315 Compilation "
        f"of Financial Information.",
        size=9, space_after=6,
    )
    _add_body_paragraph(
        doc,
        "We have applied our expertise in accounting and financial reporting to compile these "
        "financial statements in accordance with the basis of accounting described in Note 1 to "
        "the financial statements. We have complied with the relevant ethical requirements of "
        "APES 110 Code of Ethics for Professional Accountants (including Independence Standards).",
        size=9, space_after=10,
    )

    # Assurance Disclaimer
    _add_body_paragraph(doc, "Assurance Disclaimer", size=10, bold=True, space_after=6)
    _add_body_paragraph(
        doc,
        "Since a compilation engagement is not an assurance engagement, we are not required to "
        "verify the reliability, accuracy or completeness of the information provided to us by "
        f"{responsible_party.lower()} to compile these financial statements. Accordingly, we do "
        "not express an audit opinion or a review conclusion on these financial statements.",
        size=9, space_after=6,
    )
    _add_body_paragraph(
        doc,
        "The special purpose financial statements were compiled exclusively for the benefit of "
        f"{responsible_party.lower()} who is responsible for the reliability, accuracy and "
        "completeness of the information compiled therein. We do not accept responsibility for "
        "the contents of the special purpose financial statements.",
        size=9, space_after=20,
    )

    # Signature block
    _add_body_paragraph(doc, "M C & S Pty Ltd", size=10, bold=True, space_after=2)
    _add_body_paragraph(doc, "PO Box 4440", size=9, space_after=2)
    _add_body_paragraph(doc, "Dandenong South VIC 3164", size=9, space_after=10)
    _add_body_paragraph(doc, f"Dated: {date.today().strftime('%d %B %Y')}", size=9, space_after=2)

    doc.add_page_break()


# =============================================================================
# Detailed Profit and Loss Statement
# =============================================================================

def _add_detailed_pnl(doc, entity, fy):
    """Add the detailed profit and loss statement."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=6)
    _add_heading_paragraph(doc, "Detailed Profit and Loss Statement", size=12, bold=True, space_after=2)
    _add_heading_paragraph(doc, _get_period_text(fy), size=10, bold=False, space_after=10)

    # Get all P&L lines from trial balance
    lines = fy.trial_balance_lines.order_by("account_code").all()

    prior_year_label = fy.prior_year.year_label if fy.prior_year else "Prior Year"
    current_year_label = fy.year_label

    headers = ["", f"{fy.end_date.year}\n$", f"{fy.end_date.year - 1}\n$"]

    rows = []
    total_income = Decimal("0")
    total_income_prior = Decimal("0")
    total_expenses = Decimal("0")
    total_expenses_prior = Decimal("0")

    # Income section
    rows.append({"cells": ["Income", "", ""], "bold": True, "is_total": False})

    for line in lines:
        try:
            code_num = int(line.account_code)
        except ValueError:
            continue

        if 0 <= code_num < 1000 and line.closing_balance != 0:
            prior = _get_prior_balance(fy, line.account_code)
            # Revenue is typically credit (negative in TB), show as positive
            current_val = abs(line.closing_balance)
            prior_val = abs(prior)
            total_income += current_val
            total_income_prior += prior_val
            rows.append({
                "cells": [line.account_name, _fmt(current_val), _fmt(prior_val)],
                "bold": False, "indent": 1,
            })

    rows.append({
        "cells": ["Total Income", _fmt(total_income), _fmt(total_income_prior)],
        "bold": True, "is_total": True,
    })
    rows.append({"cells": ["", "", ""], "bold": False})

    # Expenses section
    rows.append({"cells": ["Expenses", "", ""], "bold": True})

    for line in lines:
        try:
            code_num = int(line.account_code)
        except ValueError:
            continue

        if 1000 <= code_num < 2000 and line.closing_balance != 0:
            prior = _get_prior_balance(fy, line.account_code)
            current_val = abs(line.closing_balance)
            prior_val = abs(prior)
            total_expenses += current_val
            total_expenses_prior += prior_val
            rows.append({
                "cells": [line.account_name, _fmt(current_val), _fmt(prior_val)],
                "bold": False, "indent": 1,
            })

    rows.append({
        "cells": ["Total Expenses", _fmt(total_expenses), _fmt(total_expenses_prior)],
        "bold": True, "is_total": True,
    })
    rows.append({"cells": ["", "", ""], "bold": False})

    # Net Profit
    net_profit = total_income - total_expenses
    net_profit_prior = total_income_prior - total_expenses_prior
    rows.append({
        "cells": [
            "Net Profit (Loss) from Ordinary Activities before income tax",
            _fmt(net_profit),
            _fmt(net_profit_prior),
        ],
        "bold": True, "is_total": True,
    })

    _add_statement_table(doc, headers, rows)
    _add_footer_text(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Detailed Balance Sheet
# =============================================================================

def _add_detailed_balance_sheet(doc, entity, fy):
    """Add the detailed balance sheet."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=6)
    _add_heading_paragraph(doc, "Detailed Balance Sheet", size=12, bold=True, space_after=2)
    _add_heading_paragraph(doc, _get_as_at_text(fy), size=10, bold=False, space_after=10)

    lines = fy.trial_balance_lines.order_by("account_code").all()
    headers = ["", f"{fy.end_date.year}\n$", f"{fy.end_date.year - 1}\n$"]
    rows = []

    # Define balance sheet sections by code range
    sections = [
        ("Current Assets", 2000, 2500),
        ("Non-Current Assets", 2500, 3000),
        ("Current Liabilities", 3000, 3500),
        ("Non-Current Liabilities", 3500, 4000),
        ("Equity", 4000, 4200),
    ]

    total_current_assets = Decimal("0")
    total_current_assets_prior = Decimal("0")
    total_noncurrent_assets = Decimal("0")
    total_noncurrent_assets_prior = Decimal("0")
    total_current_liab = Decimal("0")
    total_current_liab_prior = Decimal("0")
    total_noncurrent_liab = Decimal("0")
    total_noncurrent_liab_prior = Decimal("0")
    total_equity = Decimal("0")
    total_equity_prior = Decimal("0")

    for section_name, code_start, code_end in sections:
        section_total = Decimal("0")
        section_total_prior = Decimal("0")
        section_lines = []

        for line in lines:
            try:
                code_num = int(line.account_code)
            except ValueError:
                continue

            if code_start <= code_num < code_end and line.closing_balance != 0:
                prior = _get_prior_balance(fy, line.account_code)
                current_val = line.closing_balance
                prior_val = prior

                # Liabilities and Equity are typically credit (negative in TB), show as positive
                if "Liabilities" in section_name or section_name == "Equity":
                    current_val = abs(current_val)
                    prior_val = abs(prior_val)

                section_total += current_val
                section_total_prior += prior_val
                section_lines.append({
                    "cells": [line.account_name, _fmt(current_val), _fmt(prior_val)],
                    "bold": False, "indent": 1,
                })

        if section_lines:
            rows.append({"cells": [section_name, "", ""], "bold": True})
            rows.extend(section_lines)
            rows.append({
                "cells": [f"Total {section_name}", _fmt(section_total), _fmt(section_total_prior)],
                "bold": True, "is_total": True,
            })
            rows.append({"cells": ["", "", ""], "bold": False})

        # Track totals
        if section_name == "Current Assets":
            total_current_assets = section_total
            total_current_assets_prior = section_total_prior
        elif section_name == "Non-Current Assets":
            total_noncurrent_assets = section_total
            total_noncurrent_assets_prior = section_total_prior
        elif section_name == "Current Liabilities":
            total_current_liab = section_total
            total_current_liab_prior = section_total_prior
        elif section_name == "Non-Current Liabilities":
            total_noncurrent_liab = section_total
            total_noncurrent_liab_prior = section_total_prior
        elif section_name == "Equity":
            total_equity = section_total
            total_equity_prior = section_total_prior

    # Summary totals
    total_assets = total_current_assets + total_noncurrent_assets
    total_assets_prior = total_current_assets_prior + total_noncurrent_assets_prior
    total_liab = total_current_liab + total_noncurrent_liab
    total_liab_prior = total_current_liab_prior + total_noncurrent_liab_prior
    net_assets = total_assets - total_liab
    net_assets_prior = total_assets_prior - total_liab_prior

    rows.append({
        "cells": ["Total Assets", _fmt(total_assets), _fmt(total_assets_prior)],
        "bold": True, "is_total": True,
    })
    rows.append({
        "cells": ["Total Liabilities", _fmt(total_liab), _fmt(total_liab_prior)],
        "bold": True, "is_total": True,
    })
    rows.append({
        "cells": ["Net Assets", _fmt(net_assets), _fmt(net_assets_prior)],
        "bold": True, "is_total": True,
    })

    _add_statement_table(doc, headers, rows)
    _add_footer_text(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Summary P&L (Company only)
# =============================================================================

def _add_summary_pnl(doc, entity, fy):
    """Add the summary/statutory P&L statement (company only)."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=6)
    _add_heading_paragraph(doc, "Profit and Loss Statement", size=12, bold=True, space_after=2)
    _add_heading_paragraph(doc, _get_period_text(fy), size=10, bold=False, space_after=10)

    headers = ["", f"{fy.end_date.year}\n$", f"{fy.end_date.year - 1}\n$"]
    rows = []

    # Calculate totals directly from TB code ranges (same approach as detailed P&L)
    lines = fy.trial_balance_lines.order_by("account_code").all()
    total_revenue = Decimal("0")
    total_revenue_prior = Decimal("0")
    total_expenses = Decimal("0")
    total_expenses_prior = Decimal("0")
    tax_expense = Decimal("0")
    tax_expense_prior = Decimal("0")

    for line in lines:
        try:
            code_num = int(line.account_code)
        except ValueError:
            continue
        prior = _get_prior_balance(fy, line.account_code)
        if 0 <= code_num < 1000:  # Revenue
            total_revenue += abs(line.closing_balance)
            total_revenue_prior += abs(prior)
        elif 1000 <= code_num < 2000:  # Expenses
            total_expenses += abs(line.closing_balance)
            total_expenses_prior += abs(prior)

    profit_before_tax = total_revenue - total_expenses
    profit_before_tax_prior = total_revenue_prior - total_expenses_prior
    profit_after_tax = profit_before_tax - tax_expense
    profit_after_tax_prior = profit_before_tax_prior - tax_expense_prior

    rows.append({
        "cells": [
            "Operating profit (deficit) before income tax",
            _fmt(profit_before_tax),
            _fmt(profit_before_tax_prior),
        ],
        "bold": False,
    })
    rows.append({
        "cells": [
            "Income tax (credit) attributable to operating profit (loss)",
            _fmt(tax_expense),
            _fmt(tax_expense_prior),
        ],
        "bold": False,
    })
    rows.append({
        "cells": [
            "Operating profit (deficit) after income tax",
            _fmt(profit_after_tax),
            _fmt(profit_after_tax_prior),
        ],
        "bold": True, "is_total": True,
    })

    # Retained earnings movement - get retained earnings from equity section
    retained_earnings_opening = Decimal("0")
    retained_earnings_opening_prior = Decimal("0")
    dividends = Decimal("0")
    dividends_prior = Decimal("0")

    for line in lines:
        try:
            code_num = int(line.account_code)
        except ValueError:
            continue
        name_lower = line.account_name.lower()
        if 4000 <= code_num < 4200:
            if "retained" in name_lower:
                retained_earnings_opening = abs(line.closing_balance) - profit_after_tax
                prior_bal = _get_prior_balance(fy, line.account_code)
                retained_earnings_opening_prior = abs(prior_bal)
            elif "dividend" in name_lower:
                dividends = abs(line.closing_balance)
                dividends_prior = abs(_get_prior_balance(fy, line.account_code))

    total_available = retained_earnings_opening + profit_after_tax
    total_available_prior = retained_earnings_opening_prior + profit_after_tax_prior
    retained_end = total_available - dividends
    retained_end_prior = total_available_prior - dividends_prior

    rows.append({"cells": ["", "", ""], "bold": False})
    rows.append({
        "cells": ["Retained profits at beginning of year",
                  _fmt(retained_earnings_opening), _fmt(retained_earnings_opening_prior)],
        "bold": False,
    })
    rows.append({
        "cells": ["Total available for appropriation",
                  _fmt(total_available), _fmt(total_available_prior)],
        "bold": False,
    })
    rows.append({
        "cells": ["Dividends provided for or paid",
                  _fmt(dividends) if dividends else "-", _fmt(dividends_prior) if dividends_prior else "-"],
        "bold": False,
    })
    rows.append({
        "cells": ["Retained profits at end of financial year",
                  _fmt(retained_end), _fmt(retained_end_prior)],
        "bold": True, "is_total": True,
    })

    _add_statement_table(doc, headers, rows)
    _add_footer_text(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Partners' Profit Distribution Summary
# =============================================================================

def _add_partners_distribution(doc, entity, fy):
    """Add the partners' profit distribution summary (partnership only)."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=6)
    _add_heading_paragraph(doc, "Partners' Profit Distribution Summary", size=12, bold=True, space_after=2)
    _add_heading_paragraph(doc, _get_period_text(fy), size=10, bold=False, space_after=10)

    partners = entity.officers.filter(
        role=EntityOfficer.OfficerRole.PARTNER,
        date_ceased__isnull=True,
    ).order_by("display_order")

    # Calculate net profit from TB
    lines = fy.trial_balance_lines.all()
    total_income = Decimal("0")
    total_expenses = Decimal("0")
    for line in lines:
        try:
            code_num = int(line.account_code)
        except ValueError:
            continue
        if 0 <= code_num < 1000:
            total_income += abs(line.closing_balance)
        elif 1000 <= code_num < 2000:
            total_expenses += abs(line.closing_balance)

    net_profit = total_income - total_expenses

    headers = ["", f"{fy.end_date.year}\n$", f"{fy.end_date.year - 1}\n$"]
    rows = []

    # Distribution summary
    rows.append({"cells": ["Partners' Share of Profit", "", ""], "bold": True})
    for partner in partners:
        share_pct = partner.profit_share_percentage or Decimal("0")
        share_amount = net_profit * share_pct / Decimal("100") if share_pct else Decimal("0")
        rows.append({
            "cells": [
                f"  {partner.full_name} ({share_pct}%)",
                _fmt(share_amount),
                "-",
            ],
            "bold": False, "indent": 1,
        })

    rows.append({"cells": ["", "", ""], "bold": False})
    rows.append({
        "cells": ["Total Profit Distributed", _fmt(net_profit), "-"],
        "bold": True, "is_total": True,
    })

    _add_statement_table(doc, headers, rows)

    # Detailed per-partner movement
    doc.add_paragraph()
    _add_heading_paragraph(doc, "Partners' Capital Account Movement", size=11, bold=True, space_after=10)

    for partner in partners:
        share_pct = partner.profit_share_percentage or Decimal("0")
        share_amount = net_profit * share_pct / Decimal("100") if share_pct else Decimal("0")

        p_rows = [
            {"cells": [partner.full_name, "", ""], "bold": True},
            {"cells": ["Opening balance", "-", "-"], "bold": False, "indent": 1},
            {"cells": ["Profit distribution for year", _fmt(share_amount), "-"], "bold": False, "indent": 1},
            {"cells": ["Less: Drawings", "-", "-"], "bold": False, "indent": 1},
            {"cells": ["Closing balance", _fmt(share_amount), "-"], "bold": True, "is_total": True},
            {"cells": ["", "", ""], "bold": False},
        ]
        for r in p_rows:
            rows.append(r)

    _add_footer_text(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Declaration Page
# =============================================================================

def _add_declaration(doc, entity, fy):
    """Add the appropriate declaration page based on entity type."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=10)

    entity_type = entity.entity_type
    signatories = entity.officers.filter(
        is_signatory=True,
        date_ceased__isnull=True,
    ).order_by("display_order")

    if entity_type == "company":
        _add_heading_paragraph(doc, "Director's Declaration", size=12, bold=True, space_after=15)
        _add_body_paragraph(
            doc,
            f"The director has determined that {entity.entity_name} is not a reporting entity. "
            f"The director has determined that this special purpose financial statement should be "
            f"prepared in accordance with the accounting policies described in Note 1 to the "
            f"financial statements.",
            size=9, space_after=10,
        )
        _add_body_paragraph(
            doc,
            "The director of the company declares that:",
            size=9, space_after=6,
        )
        _add_body_paragraph(
            doc,
            "(i)  the financial statements and notes present fairly the company's financial "
            f"position as at {fy.end_date.strftime('%d %B %Y')} and its performance for the year "
            "ended on that date in accordance with the accounting policies described in Note 1 to "
            "the financial statements; and",
            size=9, space_after=6,
        )
        _add_body_paragraph(
            doc,
            "(ii) in the director's opinion there are reasonable grounds to believe that the "
            "company will be able to pay its debts as and when they become due and payable.",
            size=9, space_after=20,
        )

        # Signature blocks
        for officer in signatories:
            _add_body_paragraph(doc, "", size=9, space_after=20)  # Space for signature
            p = _add_body_paragraph(doc, "_" * 40, size=9, space_after=2)
            _add_body_paragraph(doc, officer.full_name, size=9, bold=True, space_after=2)
            title = officer.title or "Director"
            _add_body_paragraph(doc, title, size=9, space_after=10)

    elif entity_type == "trust":
        _add_heading_paragraph(doc, "Trustee's Declaration", size=12, bold=True, space_after=15)
        _add_body_paragraph(
            doc,
            f"The directors of the trustee company have determined that {entity.entity_name} "
            f"is not a reporting entity. The directors of the trustee company have determined that "
            f"this special purpose financial statement should be prepared in accordance with the "
            f"accounting policies described in Note 1 to the financial statements.",
            size=9, space_after=10,
        )
        _add_body_paragraph(doc, "The directors of the trustee company declare that:", size=9, space_after=6)
        _add_body_paragraph(
            doc,
            "(i)  the financial statements and notes present fairly the trust's financial "
            f"position as at {fy.end_date.strftime('%d %B %Y')} and its performance for the year "
            "ended on that date in accordance with the accounting policies described in Note 1; and",
            size=9, space_after=6,
        )
        _add_body_paragraph(
            doc,
            "(ii) in the directors' opinion there are reasonable grounds to believe that the "
            "trust will be able to pay its debts as and when they become due and payable.",
            size=9, space_after=20,
        )

        for officer in signatories:
            _add_body_paragraph(doc, "", size=9, space_after=20)
            _add_body_paragraph(doc, "_" * 40, size=9, space_after=2)
            _add_body_paragraph(doc, officer.full_name, size=9, bold=True, space_after=2)
            title = officer.title or "Director of the Trustee Company"
            _add_body_paragraph(doc, title, size=9, space_after=10)

    elif entity_type == "partnership":
        _add_heading_paragraph(doc, "Partner Declaration", size=12, bold=True, space_after=15)
        _add_body_paragraph(
            doc,
            f"The partners have determined that the partnership is not a reporting entity. "
            f"The partners have determined that this special purpose financial statement should "
            f"be prepared in accordance with the accounting policies described in the financial "
            f"statements.",
            size=9, space_after=10,
        )
        _add_body_paragraph(doc, "The partners declare that:", size=9, space_after=6)
        _add_body_paragraph(
            doc,
            "(a) the financial statements comply with the accounting policies described therein; and",
            size=9, space_after=6,
        )
        _add_body_paragraph(
            doc,
            "(b) the financial statements present fairly the partnership's financial position as at "
            f"{fy.end_date.strftime('%d %B %Y')} and its performance for the year ended on that date.",
            size=9, space_after=6,
        )
        _add_body_paragraph(
            doc,
            "In the partners' opinion, there are reasonable grounds to believe that the partnership "
            "will be able to pay its debts as and when they become due and payable.",
            size=9, space_after=20,
        )

        for officer in signatories:
            _add_body_paragraph(doc, "", size=9, space_after=20)
            _add_body_paragraph(doc, "_" * 40, size=9, space_after=2)
            _add_body_paragraph(doc, officer.full_name, size=9, bold=True, space_after=2)
            _add_body_paragraph(doc, "Partner", size=9, space_after=10)

    else:  # sole_trader
        _add_heading_paragraph(doc, "Proprietor's Declaration", size=12, bold=True, space_after=15)
        _add_body_paragraph(
            doc,
            f"The proprietor has determined that this special purpose financial statement should "
            f"be prepared in accordance with the accounting policies described in the financial "
            f"statements.",
            size=9, space_after=10,
        )
        _add_body_paragraph(
            doc,
            "The proprietor declares that the financial statements present fairly the business's "
            f"financial position as at {fy.end_date.strftime('%d %B %Y')} and its performance for "
            "the year ended on that date.",
            size=9, space_after=20,
        )

        for officer in signatories:
            _add_body_paragraph(doc, "", size=9, space_after=20)
            _add_body_paragraph(doc, "_" * 40, size=9, space_after=2)
            _add_body_paragraph(doc, officer.full_name, size=9, bold=True, space_after=2)
            _add_body_paragraph(doc, "Proprietor", size=9, space_after=10)

    # Date
    _add_body_paragraph(doc, f"Dated: {date.today().strftime('%d %B %Y')}", size=9, space_after=2)


# =============================================================================
# Notes to Financial Statements
# =============================================================================

def _add_notes(doc, entity, fy):
    """Add notes to the financial statements."""
    _add_heading_paragraph(doc, entity.entity_name, size=14, bold=True, space_after=2)
    if entity.abn:
        _add_heading_paragraph(doc, f"ABN {entity.abn}", size=10, bold=False, space_after=6)
    _add_heading_paragraph(doc, "Notes to the Financial Statements", size=12, bold=True, space_after=2)
    _add_heading_paragraph(doc, _get_period_text(fy), size=10, bold=False, space_after=15)

    entity_type = entity.entity_type

    # Note 1: Summary of Significant Accounting Policies
    _add_body_paragraph(doc, "Note 1: Summary of Significant Accounting Policies", size=10, bold=True, space_after=10)

    # Basis of preparation
    _add_body_paragraph(doc, "Basis of Preparation", size=9, bold=True, space_after=4)
    if entity_type == "company":
        _add_body_paragraph(
            doc,
            f"{entity.entity_name} is a company limited by shares, incorporated and domiciled in Australia. "
            f"The director has prepared the financial statements on the basis that the company is a "
            f"non-reporting entity because there are no users dependent on general purpose financial "
            f"statements. The financial statements are therefore special purpose financial statements "
            f"that have been prepared in order to meet the requirements of the Corporations Act 2001.",
            size=9, space_after=6,
        )
    elif entity_type == "trust":
        _add_body_paragraph(
            doc,
            f"The financial statements are special purpose financial statements prepared in order to "
            f"satisfy the requirements of the trust deed. The directors of the trustee company have "
            f"determined that {entity.entity_name} is not a reporting entity.",
            size=9, space_after=6,
        )
    elif entity_type == "partnership":
        _add_body_paragraph(
            doc,
            f"The financial statements are special purpose financial statements prepared in order to "
            f"satisfy the requirements of the partners. The partners have determined that "
            f"{entity.entity_name} is not a reporting entity.",
            size=9, space_after=6,
        )
    else:
        _add_body_paragraph(
            doc,
            f"The financial statements are special purpose financial statements prepared for the "
            f"sole use of the proprietor.",
            size=9, space_after=6,
        )

    _add_body_paragraph(
        doc,
        "The financial statements have been prepared in accordance with the recognition and "
        "measurement requirements of the Australian Accounting Standards, the Australian Accounting "
        "Interpretations and the significant accounting policies disclosed below, which the "
        f"{'director has' if entity_type == 'company' else 'partners have' if entity_type == 'partnership' else 'directors of the trustee company have' if entity_type == 'trust' else 'proprietor has'} "
        "determined are appropriate to meet the needs of members. Such accounting policies are "
        "consistent with the previous period unless stated otherwise.",
        size=9, space_after=6,
    )
    _add_body_paragraph(
        doc,
        "The financial statements have been prepared on an accruals basis and are based on "
        "historical costs unless otherwise stated in the notes.",
        size=9, space_after=10,
    )

    # Conditional accounting policy notes based on what exists in the trial balance
    aggregated = _aggregate_trial_balance(fy)
    policy_letter = ord("a")

    # Income Tax (company only)
    if entity_type == "company":
        _add_body_paragraph(doc, f"({chr(policy_letter)}) Income Tax", size=9, bold=True, space_after=4)
        _add_body_paragraph(
            doc,
            "The income tax expense (income) for the year comprises current income tax expense "
            "(income) and deferred tax expense (income). Current income tax expense charged to the "
            "profit or loss is the tax payable on taxable income. Deferred tax expense reflects "
            "movements in deferred tax asset and deferred tax liability balances during the year.",
            size=9, space_after=8,
        )
        policy_letter += 1

    # PPE
    has_ppe = any("NCA-001" in code for code in aggregated)
    if has_ppe:
        _add_body_paragraph(doc, f"({chr(policy_letter)}) Property, Plant and Equipment", size=9, bold=True, space_after=4)
        _add_body_paragraph(
            doc,
            "Each class of property, plant and equipment is carried at cost less, where applicable, "
            "any accumulated depreciation and impairment losses. Plant and equipment are measured on "
            "the cost basis and are therefore carried at cost less accumulated depreciation and any "
            "accumulated impairment losses.",
            size=9, space_after=4,
        )
        _add_body_paragraph(
            doc,
            "Depreciation is calculated on a diminishing value or straight line basis to write off "
            "the net cost of each item of property, plant and equipment over their expected useful "
            "lives. Depreciation rates used are reviewed annually.",
            size=9, space_after=8,
        )
        policy_letter += 1

    # Cash and Cash Equivalents
    has_cash = any("CA-001" in code for code in aggregated)
    if has_cash:
        _add_body_paragraph(doc, f"({chr(policy_letter)}) Cash and Cash Equivalents", size=9, bold=True, space_after=4)
        _add_body_paragraph(
            doc,
            "Cash and cash equivalents include cash on hand, deposits held at call with banks, "
            "other short-term highly liquid investments with original maturities of three months "
            "or less, and bank overdrafts.",
            size=9, space_after=8,
        )
        policy_letter += 1

    # Revenue
    _add_body_paragraph(doc, f"({chr(policy_letter)}) Revenue and Other Income", size=9, bold=True, space_after=4)
    _add_body_paragraph(
        doc,
        "Revenue is measured at the fair value of the consideration received or receivable after "
        "taking into account any trade discounts and volume rebates allowed. Revenue from the sale "
        "of goods is recognised at the point of delivery as this corresponds to the transfer of "
        "significant risks and rewards of ownership of the goods.",
        size=9, space_after=4,
    )
    _add_body_paragraph(
        doc,
        "Interest revenue is recognised using the effective interest method. Dividend revenue is "
        "recognised when the right to receive a dividend has been established. All revenue is "
        "stated net of the amount of goods and services tax.",
        size=9, space_after=8,
    )
    policy_letter += 1

    # GST
    _add_body_paragraph(doc, f"({chr(policy_letter)}) Goods and Services Tax (GST)", size=9, bold=True, space_after=4)
    _add_body_paragraph(
        doc,
        "Revenues, expenses and assets are recognised net of the amount of GST, except where the "
        "amount of GST incurred is not recoverable from the Australian Taxation Office (ATO). "
        "Receivables and payables are stated inclusive of the amount of GST receivable or payable. "
        "The net amount of GST recoverable from, or payable to, the ATO is included with other "
        "receivables or payables in the balance sheet.",
        size=9, space_after=8,
    )
    policy_letter += 1

    # Employee Benefits (if applicable)
    has_employee = any("EXP-008" in code or "CL-004" in code for code in aggregated)
    if has_employee and entity_type in ("company", "trust", "partnership"):
        _add_body_paragraph(doc, f"({chr(policy_letter)}) Employee Benefits", size=9, bold=True, space_after=4)
        _add_body_paragraph(
            doc,
            "Provision is made for the company's obligation for short-term employee benefits. "
            "Short-term employee benefits are benefits (other than termination benefits) that are "
            "expected to be settled wholly before 12 months after the end of the annual reporting "
            "period in which the employees render the related service. Short-term employee benefits "
            "are measured at the (undiscounted) amounts expected to be paid when the obligation is "
            "settled.",
            size=9, space_after=8,
        )
        policy_letter += 1

    _add_footer_text(doc, entity.entity_type)
    doc.add_page_break()


# =============================================================================
# Main Generation Function
# =============================================================================

def generate_financial_statements(financial_year_id) -> io.BytesIO:
    """
    Generate a complete set of financial statements for a financial year.
    Returns a BytesIO object containing the Word document.
    """
    fy = FinancialYear.objects.select_related(
        "entity", "entity__client", "prior_year"
    ).get(pk=financial_year_id)

    entity = fy.entity
    entity_type = entity.entity_type

    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Arial"
    font.size = Pt(9)

    # Set narrow margins
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    # =========================================================================
    # Build document in entity-specific order
    # =========================================================================

    # 1. Cover Page (all entity types)
    _add_cover_page(doc, entity, fy)

    # 2. Contents Page (all entity types)
    _add_contents_page(doc, entity, fy)

    # 3. Compilation Report (company: near beginning; others: near end)
    if entity_type == "company":
        _add_compilation_report(doc, entity, fy)

    # 4. Detailed P&L (all entity types)
    _add_detailed_pnl(doc, entity, fy)

    # 5. Detailed Balance Sheet (all entity types)
    _add_detailed_balance_sheet(doc, entity, fy)

    # 6. Summary P&L (company only)
    if entity_type == "company":
        _add_summary_pnl(doc, entity, fy)

    # 7. Partners' Distribution (partnership only)
    if entity_type == "partnership":
        _add_partners_distribution(doc, entity, fy)

    # 8. Notes (company and trust)
    if entity_type in ("company", "trust"):
        _add_notes(doc, entity, fy)

    # 9. Declaration (all entity types)
    _add_declaration(doc, entity, fy)

    # 10. Compilation Report (trust, partnership, sole_trader: at end)
    if entity_type != "company":
        doc.add_page_break()
        _add_compilation_report(doc, entity, fy)

    # Save to BytesIO
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer
