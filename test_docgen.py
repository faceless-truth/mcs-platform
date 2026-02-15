"""
Test script to generate a sample financial statement document.
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from decimal import Decimal
from core.models import (
    Client, Entity, FinancialYear, TrialBalanceLine,
    AccountMapping, EntityOfficer,
)
from accounts.models import User

# Get or create test data
try:
    entity = Entity.objects.filter(entity_type="company").first()
    if not entity:
        print("No company entity found. Creating test data...")
        user = User.objects.first()
        client = Client.objects.first()
        if not client:
            client = Client.objects.create(name="Test Client Pty Ltd")
        entity = Entity.objects.create(
            client=client,
            entity_name="Test Company Pty Ltd",
            entity_type="company",
            abn="12 345 678 901",
        )

    fy = entity.financial_years.first()
    if not fy:
        from datetime import date
        fy = FinancialYear.objects.create(
            entity=entity,
            year_label="FY2026",
            start_date=date(2025, 7, 1),
            end_date=date(2026, 6, 30),
        )

    # Create sample trial balance lines if none exist
    if not fy.trial_balance_lines.exists():
        print("Creating sample trial balance lines...")
        sample_lines = [
            # Revenue
            ("0100", "Sales Revenue", Decimal("-250000.00")),
            ("0200", "Interest Received", Decimal("-1500.00")),
            ("0300", "Other Income", Decimal("-5000.00")),
            # Expenses
            ("1010", "Accountancy Fees", Decimal("8500.00")),
            ("1020", "Advertising", Decimal("3200.00")),
            ("1030", "Bank Charges", Decimal("450.00")),
            ("1040", "Depreciation", Decimal("12000.00")),
            ("1050", "Insurance", Decimal("6800.00")),
            ("1060", "Motor Vehicle Expenses", Decimal("4500.00")),
            ("1070", "Rent", Decimal("36000.00")),
            ("1080", "Salaries & Wages", Decimal("95000.00")),
            ("1090", "Superannuation", Decimal("10450.00")),
            ("1100", "Telephone", Decimal("2400.00")),
            ("1110", "Other Expenses", Decimal("1800.00")),
            # Current Assets
            ("2010", "Cash at Bank - CBA", Decimal("45000.00")),
            ("2020", "Trade Debtors", Decimal("32000.00")),
            ("2030", "Prepayments", Decimal("2400.00")),
            # Non-Current Assets
            ("2510", "Plant & Equipment at Cost", Decimal("85000.00")),
            ("2520", "Less: Accumulated Depreciation - P&E", Decimal("-35000.00")),
            ("2530", "Motor Vehicle at Cost", Decimal("45000.00")),
            ("2540", "Less: Accumulated Depreciation - MV", Decimal("-18000.00")),
            # Current Liabilities
            ("3010", "Trade Creditors", Decimal("-15000.00")),
            ("3020", "GST Payable", Decimal("-8500.00")),
            ("3030", "PAYG Withholding", Decimal("-4200.00")),
            ("3040", "Provision for Annual Leave", Decimal("-6500.00")),
            ("3050", "Provision for Tax", Decimal("-12000.00")),
            # Equity
            ("4010", "Issued Capital", Decimal("-100.00")),
            ("4020", "Retained Earnings", Decimal("-100000.00")),
        ]

        for code, name, balance in sample_lines:
            TrialBalanceLine.objects.create(
                financial_year=fy,
                account_code=code,
                account_name=name,
                opening_balance=Decimal("0"),
                debit=abs(balance) if balance > 0 else Decimal("0"),
                credit=abs(balance) if balance < 0 else Decimal("0"),
                closing_balance=balance,
            )
        print(f"Created {len(sample_lines)} trial balance lines.")

    # Create officers if none exist
    if not entity.officers.exists():
        print("Creating sample officers...")
        EntityOfficer.objects.create(
            entity=entity,
            full_name="James Smith",
            role=EntityOfficer.OfficerRole.DIRECTOR,
            title="Managing Director",
            is_signatory=True,
            display_order=1,
        )
        EntityOfficer.objects.create(
            entity=entity,
            full_name="Sarah Johnson",
            role=EntityOfficer.OfficerRole.DIRECTOR,
            title="Director",
            is_signatory=True,
            display_order=2,
        )
        print("Created 2 directors.")

    print(f"\nGenerating financial statements for: {entity.entity_name}")
    print(f"Financial Year: {fy.year_label}")
    print(f"Entity Type: {entity.entity_type}")
    print(f"TB Lines: {fy.trial_balance_lines.count()}")
    print(f"Officers: {entity.officers.count()}")

    from core.docgen import generate_financial_statements

    buffer = generate_financial_statements(fy.pk)

    output_path = "/home/ubuntu/mcs-platform/test_output.docx"
    with open(output_path, "wb") as f:
        f.write(buffer.getvalue())

    print(f"\nDocument generated successfully: {output_path}")
    print(f"File size: {os.path.getsize(output_path):,} bytes")

except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()
