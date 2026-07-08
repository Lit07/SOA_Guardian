import os
import csv
import pytest
from soa_guardian.pipeline import process_statement
from soa_guardian.vendor_registry import VendorRegistry

def create_no_header_csv(file_path: str):
    """Creates a csv statement that contains only unstructured text with no header table."""
    data = [
        ["Contact Person: Jane Doe"],
        ["Phone Support: +1-555-0199"],
        ["Some random footer information page 1"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(data)

def create_pagemill_description_csv(file_path: str):
    """Creates a csv statement with a valid transaction containing the word 'Page' in description."""
    data = [
        ["Opening Balance: 100.00"],
        ["Closing Balance: 200.00"],
        [],
        ["Date", "Description", "Dr", "Cr", "Balance"],
        ["01/06/2026", "Opening Balance", "", "", "100.00"],
        ["02/06/2026", "PageMill Software License purchase", "", "100.00", "200.00"],
        [],
        ["Page 1 of 1"]
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(data)

def test_no_header_prevents_crash():
    """Verify that statements with no headers do not crash Pydantic, but flag unparsed lines."""
    csv_path = "tests/no_header_test.csv"
    create_no_header_csv(csv_path)
    
    try:
        canonical = process_statement(csv_path)
        
        # Verify it did not crash and parsed empty transactions
        assert len(canonical.transactions) == 0
        assert canonical.review_required
        assert len(canonical.unparsed_lines) > 0
        assert canonical.unparsed_lines[0].reason == "No table header identified yet"
        
        # Warn about opening and closing balances being default 0.0
        assert any("Opening balance boundary extraction failed" in f for f in canonical.anomaly_flags)
        assert any("Closing balance boundary extraction failed" in f for f in canonical.anomaly_flags)
        
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

def test_pagemill_transaction_not_swallowed():
    """Verify that transactions containing the word 'page' in description are not swallowed as footer lines."""
    csv_path = "tests/pagemill_test.csv"
    create_pagemill_description_csv(csv_path)
    
    try:
        canonical = process_statement(csv_path)
        
        # Should successfully parse 2 transactions: Opening and PageMill Software License
        assert len(canonical.transactions) == 2
        assert canonical.transactions[1].description == "PageMill Software License purchase"
        assert canonical.transactions[1].credit_amount == 100.00
        assert not canonical.review_required
        
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

def test_vendor_registry_relative_discovery():
    """Verify registry search path autoloader resolves mappings relative to file module roots."""
    registry = VendorRegistry()
    # It should dynamically find registry configurations from the root folder
    assert registry.vendors is not None
