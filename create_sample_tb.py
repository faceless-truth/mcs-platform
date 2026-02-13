"""Create a sample trial balance Excel file for testing."""
import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Trial Balance"

# Header row
headers = ["Account Code", "Account Name", "Opening Balance", "Debit", "Credit"]
ws.append(headers)

# Sample data for a small company
data = [
    ("1000", "Cash at Bank - CBA", 45230.00, 125000.00, 98500.00),
    ("1100", "Trade Debtors", 12400.00, 180000.00, 175000.00),
    ("1200", "Inventory", 8500.00, 25000.00, 22000.00),
    ("1300", "Prepayments", 3200.00, 6000.00, 5800.00),
    ("1500", "Office Equipment", 15000.00, 5000.00, 0.00),
    ("1510", "Accum Depreciation - Office Equipment", -3000.00, 0.00, 2500.00),
    ("1600", "Motor Vehicle", 35000.00, 0.00, 0.00),
    ("1610", "Accum Depreciation - Motor Vehicle", -7000.00, 0.00, 5000.00),
    ("2000", "Trade Creditors", -8500.00, 95000.00, 102000.00),
    ("2100", "GST Payable", -2100.00, 12000.00, 14500.00),
    ("2200", "PAYG Withholding", -1800.00, 18000.00, 19200.00),
    ("2300", "Provision for Annual Leave", -4500.00, 2000.00, 3500.00),
    ("2400", "Provision for Long Service Leave", -2200.00, 0.00, 800.00),
    ("2500", "Income Tax Payable", -3500.00, 3500.00, 8200.00),
    ("3000", "Share Capital", -10000.00, 0.00, 0.00),
    ("3100", "Retained Earnings", -52230.00, 0.00, 0.00),
    ("4000", "Revenue - Sales", 0.00, 0.00, 350000.00),
    ("4100", "Revenue - Services", 0.00, 0.00, 85000.00),
    ("4200", "Interest Income", 0.00, 0.00, 1200.00),
    ("5000", "Salaries & Wages", 0.00, 180000.00, 0.00),
    ("5100", "Superannuation", 0.00, 19800.00, 0.00),
    ("5200", "Workers Compensation", 0.00, 3600.00, 0.00),
    ("6000", "Rent", 0.00, 36000.00, 0.00),
    ("6100", "Office Supplies", 0.00, 4800.00, 0.00),
    ("6200", "Telephone & Internet", 0.00, 3600.00, 0.00),
    ("6300", "Insurance", 0.00, 5400.00, 0.00),
    ("6400", "Motor Vehicle Expenses", 0.00, 8200.00, 0.00),
    ("6500", "Professional Fees", 0.00, 12000.00, 0.00),
    ("6600", "Depreciation", 0.00, 7500.00, 0.00),
    ("6700", "Bank Charges", 0.00, 1200.00, 0.00),
    ("6800", "Other Expenses", 0.00, 2400.00, 0.00),
    ("7000", "Interest Expense", 0.00, 1500.00, 0.00),
    ("8000", "Income Tax Expense", 0.00, 8200.00, 0.00),
]

for row in data:
    ws.append(row)

# Format columns
for col in ['C', 'D', 'E']:
    for cell in ws[col][1:]:
        cell.number_format = '#,##0.00'

# Auto-width
for col in ws.columns:
    max_length = max(len(str(cell.value or "")) for cell in col)
    ws.column_dimensions[col[0].column_letter].width = max_length + 2

wb.save("static/sample_trial_balance.xlsx")
print("Sample trial balance created: static/sample_trial_balance.xlsx")
