"""
Test document generation with real Firestop Victoria Pty Ltd data.
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from decimal import Decimal
from datetime import date
from core.models import Client, Entity, FinancialYear, TrialBalanceLine, EntityOfficer

# Clean up any existing test data
TrialBalanceLine.objects.filter(financial_year__entity__entity_name="Firestop Victoria Pty Ltd").delete()
FinancialYear.objects.filter(entity__entity_name="Firestop Victoria Pty Ltd").delete()
EntityOfficer.objects.filter(entity__entity_name="Firestop Victoria Pty Ltd").delete()
Entity.objects.filter(entity_name="Firestop Victoria Pty Ltd").delete()
Client.objects.filter(name="Firestop Victoria").delete()

# Create client and entity
client = Client.objects.create(
    name="Firestop Victoria",
    contact_email="john@firestopvic.com.au",
)

entity = Entity.objects.create(
    client=client,
    entity_name="Firestop Victoria Pty Ltd",
    entity_type="company",
    abn="57 676 406 312",
)

# Add director
EntityOfficer.objects.create(
    entity=entity,
    full_name="John Smith",
    role=EntityOfficer.OfficerRole.DIRECTOR,
    is_signatory=True,
    display_order=1,
    date_appointed=date(2020, 1, 1),
)

# Create financial year
fy = FinancialYear.objects.create(
    entity=entity,
    year_label="FY2025",
    start_date=date(2024, 7, 1),
    end_date=date(2025, 6, 30),
    status="draft",
)

# Import real trial balance data from FIRE0001.xlsx
# Data extracted from the real file:
tb_data = [
    # Income
    ("0630", "Sales", Decimal("0"), Decimal("60356")),  # Credit
    # Expenses
    ("1515", "Advertising & promotion", Decimal("58.32"), Decimal("0")),
    ("1617", "Depreciation - Other", Decimal("1018"), Decimal("0")),
    ("1755", "Insurance", Decimal("1182.55"), Decimal("0")),
    ("1800", "Materials & supplies", Decimal("53915"), Decimal("0")),
    ("1840", "Printing & stationery", Decimal("90.90"), Decimal("0")),
    ("1940", "Telephone", Decimal("259.06"), Decimal("0")),
    ("1945", "Tools", Decimal("3359.42"), Decimal("0")),
    ("1950", "Travel, accommodation & conference", Decimal("797.49"), Decimal("0")),
    ("1951", "Uniform", Decimal("975.84"), Decimal("0")),
    # Current Assets
    ("2000", "Cash at bank", Decimal("38560.88"), Decimal("0")),
    # Non-Current Assets
    ("2870", "Office equipment", Decimal("1018.18"), Decimal("0")),
    ("2875", "Less: Accumulated amortisation", Decimal("0"), Decimal("1018")),
    # Current Liabilities
    ("3380", "GST payable control account", Decimal("0"), Decimal("587.65")),
    # Non-Current Liabilities
    ("3565", "Loan - Director", Decimal("0"), Decimal("39273.98")),
]

for code, name, debit, credit in tb_data:
    # closing_balance = debit - credit (standard accounting sign convention)
    closing = debit - credit
    TrialBalanceLine.objects.create(
        financial_year=fy,
        account_code=code,
        account_name=name,
        debit=debit,
        credit=credit,
        closing_balance=closing,
    )

print(f"Created entity: {entity.entity_name}")
print(f"Created FY: {fy.year_label}")
print(f"Created {TrialBalanceLine.objects.filter(financial_year=fy).count()} TB lines")

# Generate document
from core.docgen import generate_financial_statements

buffer = generate_financial_statements(fy.pk)

output_path = os.path.join(os.path.dirname(__file__), "test_firestop_output.docx")
with open(output_path, "wb") as f:
    f.write(buffer.read())

print(f"\nDocument generated: {output_path}")
print("Done!")
