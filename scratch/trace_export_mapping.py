"""Trace exactly what resolve_cell_value returns for each column."""
import sys, os
sys.path.insert(0, ".")

from soa_guardian.pipeline import fuzzy_match_headers

# Original headers from the CHEW_S PDF statement
original_headers = ["DATE", "DOC NO.", "TYPE", "PO NO.", "DEBIT", "CREDIT", "BALANCE"]

# The mapping registry output_format_columns for CHEW_S
output_format_columns = {
    'Invoice no': 'document no',
    'Date': 'date',
    'po number': 'po number',
    'amount': 'debit/credit',
    'Doc Type': 'Type',
    'Reference': 'document no'
}

# header_mapping from pipeline parsing
header_mapping = {
    "transaction_date": 0,  # DATE
    "description": 1,       # DOC NO.
    "debit_amount": 4,      # DEBIT
    "credit_amount": 5,     # CREDIT
    "running_balance": 6    # BALANCE
}

print("=== Fuzzy match tests ===")
test_pairs = [
    ("PO NO.", "po number"),
    ("TYPE", "Type"),
    ("DOC NO.", "document no"),
    ("DEBIT", "debit/credit"),
    ("CREDIT", "debit/credit"),
    ("DATE", "date"),
]
for h1, h2 in test_pairs:
    result = fuzzy_match_headers(h1, h2)
    print(f"  fuzzy_match_headers('{h1}', '{h2}') = {result}")

print("\n=== resolve_cell_value trace ===")
from soa_guardian.exporter import resolve_cell_value
from soa_guardian.models import Transaction

tx = Transaction(
    transaction_date="06/05/24",
    description="24024887",
    debit_amount=85.34,
    credit_amount=None,
    running_balance=85.34,
    status="clean",
    confidence=1.0,
    additional_fields={"2": "Invoice", "3": "56157549"}
)

template_headers = ["Invoice no", "Date", "po number", "amount", "Doc Type", "Reference"]

for col_name in template_headers:
    val, is_numeric = resolve_cell_value(
        tx, col_name, output_format_columns, original_headers, header_mapping
    )
    print(f"  '{col_name}' -> val={val!r}, is_numeric={is_numeric}")
