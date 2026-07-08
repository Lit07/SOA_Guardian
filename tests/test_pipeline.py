import os
import pytest
from soa_guardian.pipeline import process_statement

def test_clean_pdf_pipeline():
    """Test full digital PDF pipeline on clean statement."""
    file_path = "tests/clean_pdf_statement.pdf"
    assert os.path.exists(file_path)
    
    canonical = process_statement(file_path)
    
    # Assert metadata parsing
    assert canonical.statement_metadata.bank_name == "SoA Guardian Bank"
    assert canonical.statement_metadata.account_number == "987654321"
    assert canonical.opening_balance == 1000.00
    assert canonical.closing_balance == 3095.25
    
    # Assert transactions and anchor grouping
    assert len(canonical.transactions) == 5
    assert canonical.transactions[2].description == "Grocery Shop Supermarket Store #55"
    assert canonical.transactions[2].debit_amount == 120.50
    assert canonical.transactions[2].status == "clean"
    
    # Verify triage and review statuses
    assert not canonical.anomaly_flags
    assert not canonical.review_required
    assert not canonical.repair_log

def test_corrupt_pdf_pipeline():
    """Test full digital PDF pipeline and repair loop on corrupted statement."""
    file_path = "tests/corrupt_pdf_statement.pdf"
    assert os.path.exists(file_path)
    
    canonical = process_statement(file_path)
    
    # Verify balances
    assert canonical.opening_balance == 1000.00
    assert canonical.closing_balance == 3095.25
    
    # Verify auto-repair corrected the value "12O.50" to "120.50"
    assert len(canonical.transactions) == 5
    assert canonical.transactions[2].status == "auto_repaired"
    assert canonical.transactions[2].debit_amount == 120.50
    assert canonical.transactions[2].repair_info is not None
    assert canonical.transactions[2].repair_info.corrected_value == "120.50"
    
    # Verify audit tracking
    assert len(canonical.repair_log) == 1
    assert canonical.repair_log[0]["corrected_value"] == "120.50"
    assert not canonical.review_required
    assert not canonical.anomaly_flags

def test_clean_xlsx_pipeline():
    """Test full Excel spreadsheet extraction pipeline."""
    file_path = "tests/clean_statement.xlsx"
    assert os.path.exists(file_path)
    
    canonical = process_statement(file_path)
    
    assert canonical.opening_balance == 1000.00
    assert canonical.closing_balance == 3095.25
    assert len(canonical.transactions) == 5
    assert canonical.transactions[0].description == "Opening Balance"
    assert not canonical.review_required
    assert not canonical.anomaly_flags

def test_clean_csv_pipeline():
    """Test full CSV spreadsheet extraction pipeline."""
    file_path = "tests/clean_statement.csv"
    assert os.path.exists(file_path)
    
    canonical = process_statement(file_path)
    
    assert canonical.opening_balance == 1000.00
    assert canonical.closing_balance == 3095.25
    assert len(canonical.transactions) == 5
    assert canonical.transactions[1].description == "Salary Credit"
    assert not canonical.review_required
    assert not canonical.anomaly_flags
