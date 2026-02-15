"""
Seed the AccountMapping table with standard financial statement line items
based on the Access Ledger chart of accounts structure.

These mappings define how trial balance accounts roll up into
financial statement line items for all entity types.
"""
from django.core.management.base import BaseCommand
from core.models import AccountMapping


MAPPINGS = [
    # =========================================================================
    # INCOME STATEMENT — Revenue
    # =========================================================================
    {
        "standard_code": "IS-REV-001",
        "line_item_label": "Revenue",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 100,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-002",
        "line_item_label": "Other income",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 110,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-003",
        "line_item_label": "Interest received",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 120,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-004",
        "line_item_label": "Dividend income",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 130,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-005",
        "line_item_label": "Rental income",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 140,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-006",
        "line_item_label": "Gain on disposal of assets",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 150,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-REV-007",
        "line_item_label": "Distribution income",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 160,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-REV-008",
        "line_item_label": "Government subsidies",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 170,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-REV-009",
        "line_item_label": "Capital gains",
        "financial_statement": "income_statement",
        "statement_section": "Revenue",
        "display_order": 180,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },

    # =========================================================================
    # INCOME STATEMENT — Cost of Sales
    # =========================================================================
    {
        "standard_code": "IS-COS-001",
        "line_item_label": "Cost of sales",
        "financial_statement": "income_statement",
        "statement_section": "Cost of Sales",
        "display_order": 200,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-COS-002",
        "line_item_label": "Opening stock",
        "financial_statement": "income_statement",
        "statement_section": "Cost of Sales",
        "display_order": 210,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-COS-003",
        "line_item_label": "Purchases",
        "financial_statement": "income_statement",
        "statement_section": "Cost of Sales",
        "display_order": 220,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-COS-004",
        "line_item_label": "Closing stock",
        "financial_statement": "income_statement",
        "statement_section": "Cost of Sales",
        "display_order": 230,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },

    # =========================================================================
    # INCOME STATEMENT — Expenses
    # =========================================================================
    {
        "standard_code": "IS-EXP-001",
        "line_item_label": "Accounting and professional fees",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 300,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-002",
        "line_item_label": "Advertising and promotion",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 310,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-003",
        "line_item_label": "Bad debts",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 320,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-004",
        "line_item_label": "Bank charges",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 330,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-005",
        "line_item_label": "Borrowing costs",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 340,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-006",
        "line_item_label": "Contractor and subcontractor expenses",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 350,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-007",
        "line_item_label": "Depreciation and amortisation",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 360,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-008",
        "line_item_label": "Employee benefits expense",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 370,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-009",
        "line_item_label": "Insurance",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 380,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-010",
        "line_item_label": "Motor vehicle expenses",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 390,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-011",
        "line_item_label": "Occupancy expenses",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 400,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-012",
        "line_item_label": "Repairs and maintenance",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 410,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-013",
        "line_item_label": "Telephone and communications",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 420,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-014",
        "line_item_label": "Travel and accommodation",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 430,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-015",
        "line_item_label": "Utilities",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 440,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-016",
        "line_item_label": "Other expenses",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 450,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "IS-EXP-017",
        "line_item_label": "Superannuation",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 460,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-018",
        "line_item_label": "Rent expense",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 470,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "IS-EXP-019",
        "line_item_label": "Loss on disposal of assets",
        "financial_statement": "income_statement",
        "statement_section": "Expenses",
        "display_order": 480,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },

    # =========================================================================
    # INCOME STATEMENT — Tax
    # =========================================================================
    {
        "standard_code": "IS-TAX-001",
        "line_item_label": "Income tax expense",
        "financial_statement": "income_statement",
        "statement_section": "Income Tax",
        "display_order": 900,
        "applicable_entities": ["company"],
    },

    # =========================================================================
    # BALANCE SHEET — Current Assets
    # =========================================================================
    {
        "standard_code": "BS-CA-001",
        "line_item_label": "Cash and cash equivalents",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 100,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CA-002",
        "line_item_label": "Trade and other receivables",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 110,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CA-003",
        "line_item_label": "Inventories",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 120,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-CA-004",
        "line_item_label": "Financial assets",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 130,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CA-005",
        "line_item_label": "Other current assets",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 140,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CA-006",
        "line_item_label": "Prepayments",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 150,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-CA-007",
        "line_item_label": "Loans to related parties",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Assets",
        "display_order": 160,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },

    # =========================================================================
    # BALANCE SHEET — Non-Current Assets
    # =========================================================================
    {
        "standard_code": "BS-NCA-001",
        "line_item_label": "Property, plant and equipment",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 200,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-NCA-002",
        "line_item_label": "Investment property",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 210,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-NCA-003",
        "line_item_label": "Intangible assets",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 220,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-NCA-004",
        "line_item_label": "Financial assets (non-current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 230,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-NCA-005",
        "line_item_label": "Deferred tax assets",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 240,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-NCA-006",
        "line_item_label": "Loans to related parties (non-current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 250,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-NCA-007",
        "line_item_label": "Other non-current assets",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Assets",
        "display_order": 260,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },

    # =========================================================================
    # BALANCE SHEET — Current Liabilities
    # =========================================================================
    {
        "standard_code": "BS-CL-001",
        "line_item_label": "Trade and other payables",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 300,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CL-002",
        "line_item_label": "Borrowings (current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 310,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CL-003",
        "line_item_label": "Current tax liabilities",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 320,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-CL-004",
        "line_item_label": "Employee benefit provisions",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 330,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-CL-005",
        "line_item_label": "Other current liabilities",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 340,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-CL-006",
        "line_item_label": "GST payable",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 350,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-CL-007",
        "line_item_label": "Lease liabilities (current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 360,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-CL-008",
        "line_item_label": "Loans from related parties (current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Current Liabilities",
        "display_order": 370,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },

    # =========================================================================
    # BALANCE SHEET — Non-Current Liabilities
    # =========================================================================
    {
        "standard_code": "BS-NCL-001",
        "line_item_label": "Borrowings (non-current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Liabilities",
        "display_order": 400,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },
    {
        "standard_code": "BS-NCL-002",
        "line_item_label": "Deferred tax liabilities",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Liabilities",
        "display_order": 410,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-NCL-003",
        "line_item_label": "Lease liabilities (non-current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Liabilities",
        "display_order": 420,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-NCL-004",
        "line_item_label": "Loans from related parties (non-current)",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Liabilities",
        "display_order": 430,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader"],
    },
    {
        "standard_code": "BS-NCL-005",
        "line_item_label": "Other non-current liabilities",
        "financial_statement": "balance_sheet",
        "statement_section": "Non-Current Liabilities",
        "display_order": 440,
        "applicable_entities": ["company", "trust", "partnership", "sole_trader", "smsf"],
    },

    # =========================================================================
    # BALANCE SHEET — Equity
    # =========================================================================
    {
        "standard_code": "BS-EQ-001",
        "line_item_label": "Issued capital",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 500,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-EQ-002",
        "line_item_label": "Retained earnings",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 510,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-EQ-003",
        "line_item_label": "Reserves",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 520,
        "applicable_entities": ["company"],
    },
    {
        "standard_code": "BS-EQ-004",
        "line_item_label": "Trust corpus / capital",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 500,
        "applicable_entities": ["trust"],
    },
    {
        "standard_code": "BS-EQ-005",
        "line_item_label": "Undistributed income",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 510,
        "applicable_entities": ["trust"],
    },
    {
        "standard_code": "BS-EQ-006",
        "line_item_label": "Partners' capital accounts",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 500,
        "applicable_entities": ["partnership"],
    },
    {
        "standard_code": "BS-EQ-007",
        "line_item_label": "Partners' current accounts",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 510,
        "applicable_entities": ["partnership"],
    },
    {
        "standard_code": "BS-EQ-008",
        "line_item_label": "Proprietor's equity",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 500,
        "applicable_entities": ["sole_trader"],
    },
    {
        "standard_code": "BS-EQ-009",
        "line_item_label": "Drawings",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 520,
        "applicable_entities": ["sole_trader", "partnership"],
    },
    {
        "standard_code": "BS-EQ-010",
        "line_item_label": "Dividends paid/provided",
        "financial_statement": "balance_sheet",
        "statement_section": "Equity",
        "display_order": 530,
        "applicable_entities": ["company"],
    },
]


class Command(BaseCommand):
    help = "Seed the AccountMapping table with standard financial statement line items"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing mappings before seeding",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            deleted_count = AccountMapping.objects.all().delete()[0]
            self.stdout.write(f"Deleted {deleted_count} existing mappings.")

        created = 0
        updated = 0
        for m in MAPPINGS:
            obj, was_created = AccountMapping.objects.update_or_create(
                standard_code=m["standard_code"],
                defaults={
                    "line_item_label": m["line_item_label"],
                    "financial_statement": m["financial_statement"],
                    "statement_section": m["statement_section"],
                    "display_order": m["display_order"],
                    "applicable_entities": m["applicable_entities"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated. "
                f"Total mappings: {AccountMapping.objects.count()}"
            )
        )
