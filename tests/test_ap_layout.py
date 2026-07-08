import pytest
from soa_guardian.grouping import group_wrapped_rows
from soa_guardian.validator import validate_statement

def test_omitted_date_transaction_carry_forward():
    """Verify that rows lacking a date but containing numbers are treated as separate transactions (date carried forward) instead of swallowed."""
    header_mapping = {
        "transaction_date": 0,
        "description": 1,
        "debit_amount": 2,
        "credit_amount": 3,
        "running_balance": 4
    }
    
    rows = [
        ["23.09.2024", "Invoice PH24003863", "5335.33", "", "5335.33"],
        # Row lacking a date but containing credit and balance -> treated as a transaction row, date carried forward!
        ["", "GST refund diff", "", "-1020.98", "4314.35"],
        # Row lacking a date and containing NO numeric values -> treated as a description continuation wrap!
        ["", "Details for GST check", "", "", ""],
        ["03/10/2024", "Invoice PH24003411", "1225.33", "", "5539.68"]
    ]
    
    grouped = group_wrapped_rows(rows, header_mapping)
    
    # Should result in exactly 3 logical rows (Row 2 GST refund is kept separate, Row 3 is merged into Row 2)
    assert len(grouped) == 3
    
    # Verify date carry-forward
    assert grouped[0][0] == "23.09.2024"
    assert grouped[1][0] == "23.09.2024"
    assert grouped[2][0] == "03/10/2024"
    
    # Verify continuation description merge
    assert grouped[1][1] == "GST refund diff Details for GST check"
    assert grouped[1][3] == "-1020.98"
    assert grouped[1][4] == "4314.35"

def test_sign_convention_auto_detection():
    """Verify that validator auto-detects different credit/debit sign conventions (signed columns vs AP format)."""
    # 1. Config C: Balance = Prev + Credit + Debit (signed layout)
    txs_signed = [
        {"debit_amount": "5335.33", "credit_amount": "", "running_balance": "5335.33"},
        {"debit_amount": "", "credit_amount": "-1020.98", "running_balance": "4314.35"},
        {"debit_amount": "1225.33", "credit_amount": "", "running_balance": "5539.68"},
    ]
    
    df, overall_ok, flags = validate_statement(
        opening_balance=0.0,
        closing_balance=5539.68,
        transactions=txs_signed,
        locale="period_decimal"
    )
    
    assert overall_ok
    assert all(df["status"] == "clean")

    # 2. Config B: Balance = Prev - Credit + Debit (Accounts Payable vendor layout)
    txs_ap = [
        {"debit_amount": "500.00", "credit_amount": "", "running_balance": "500.00"},
        {"debit_amount": "", "credit_amount": "200.00", "running_balance": "300.00"},
        {"debit_amount": "1000.00", "credit_amount": "", "running_balance": "1300.00"},
    ]
    
    df_ap, overall_ok_ap, flags_ap = validate_statement(
        opening_balance=0.0,
        closing_balance=1300.00,
        transactions=txs_ap,
        locale="period_decimal"
    )
    
    assert overall_ok_ap
    assert all(df_ap["status"] == "clean")

def test_ntuc_vendor_layout_pipeline():
    """Test full integration parsing for vendor sheets containing UEN, customer details, split header, and signed math."""
    import os
    import openpyxl
    from soa_guardian.pipeline import process_statement

    test_xlsx = "tests/ntuc_test.xlsx"
    
    # Replicate the exact grid shown in the NTUC screenshot
    data = [
        ["CROWN PACIF", "IC BEVERAGE", "PTE", "LTD", "", "", "", "", "", "Date printed", "", ": 18.06.2026"],
        ["26 Tuas Ave", "nue 12 Sing", "apore", "639042", "", "", "", "", "", "Time printed", "", ": 15:09:41"],
        ["Tel: 6861", "-717", "", "", "", "", "", "", "", "Page", "", ": 1 of 257"],
        ["Fax: 6861", "-771", "", "", "", "", "", "", "", "", "", ""],
        ["UEN & Gst R", "eg No : 20", "14081 29G", "", "", "", "", "", "", "", "", ""],
        ["statement Rep", "ort", "", "", "", "", "", "", "", "", "", ""],
        ["between :", "1.05.2026 to", "31.05.2026", "", "", "", "", "", "", "", "", ""],
        ["Transaction", "", "", "", "", "", "", "", "", "", "", ""],
        ["Customer :", "NTUC Fairpr", "ice C", "o-Operati", "ve LTD", "", "", "", "", "Customer", "Id :", "3000776"],
        ["1 Joo Koon", "Circl", "e #13-01", "", "29117", "", "", "", "", "Salesman", "Id :", "6000"],
        ["SINGAPORE 6", "5035", "", "", "", "", "", "", "", "Term Cod", "e :", "60"],
        ["Phone : 984", "3 Fax : 6458 8", "975", "", "", "", "", "", "", "", "", ""],
        [],
        ["", "", "", "Remark", "", "", "Debit", "", "Credit", "Balance"],
        ["Tran Date", "Due Date", "Type", "", "", "", "", "", "", ""],
        ["23.09.2024", "22.11.2024", "RV", "Invoice PH24003863", "", "", "5,335.33", "", "", "5,335.33"],
        # Same-date transaction row with empty date and credit and balance values
        ["", "03.04.2024", "DA", "GST refund diff", "", "", "", "", "-1,020.98", "4,314.35"],
        # Continuation wrap for description
        ["", "", "", "Details for check", "", "", "", "", "", ""],
        ["03.10.2024", "11.02.2025", "RV", "Invoice PH24003411", "", "", "1,225.33", "", "", "5,539.68"],
        ["Opening Balance: 0.00", "", "", "", "", "", "", "", "", ""],
        ["Closing Balance: 5,539.68", "", "", "", "", "", "", "", "", ""]
    ]
    
    # Save test XLSX
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for r in data:
        ws.append(r)
    wb.save(test_xlsx)
    
    try:
        canonical = process_statement(test_xlsx)
        
        # Verify metadata
        metadata = canonical.statement_metadata
        assert "CROWN PACIF" in metadata.vendor_name
        assert "IC BEVERAGE" in metadata.vendor_name
        assert metadata.uen == "201408129G"
        assert metadata.customer_id == "3000776"
        assert metadata.salesman_id == "6000"
        assert metadata.term_code == "60"
        
        # Verify transactions
        txs = canonical.transactions
        # Should parse exactly 3 transactions:
        # 1. Invoice PH24003863
        # 2. GST refund diff (with Details for check appended)
        # 3. Invoice PH24003411
        assert len(txs) == 3
        
        assert txs[0].transaction_date == "23.09.2024"
        assert txs[0].debit_amount == 5335.33
        assert txs[0].credit_amount is None
        assert txs[0].running_balance == 5335.33
        
        # Date carry-forward and text wrap verification
        assert txs[1].transaction_date == "23.09.2024"
        assert txs[1].description == "GST refund diff Details for check"
        assert txs[1].debit_amount is None
        assert txs[1].credit_amount == -1020.98
        assert txs[1].running_balance == 4314.35
        
        assert txs[2].transaction_date == "03.10.2024"
        assert txs[2].debit_amount == 1225.33
        assert txs[2].running_balance == 5539.68
        
        # Math verification
        assert len(canonical.anomaly_flags) == 0
        assert canonical.opening_balance == 0.0
        assert canonical.closing_balance == 5539.68
        
    finally:
        if os.path.exists(test_xlsx):
            try:
                os.remove(test_xlsx)
            except PermissionError:
                pass
