import pytest
from soa_guardian.validator import parse_currency, generate_candidates, validate_statement, repair_and_triage
from soa_guardian.grouping import group_wrapped_rows
from soa_guardian.recovery import merge_split_headers, recover_cell_traversal
from soa_guardian.retrieval import retrieve_relevant_pages

def test_currency_parsing():
    """Verify robust currency string parsing across locales."""
    assert parse_currency("1,234.56", "period_decimal") == 1234.56
    assert parse_currency("1.234,56", "comma_decimal") == 1234.56
    assert parse_currency("$ 120.50", "period_decimal") == 120.50
    assert parse_currency("", "period_decimal") == 0.0
    assert parse_currency(None) == 0.0

def test_candidate_generation():
    """Verify confusable OCR digit substitution generation."""
    candidates = generate_candidates("12O.50")
    assert "120.50" in candidates
    
    candidates_s = generate_candidates("3S0.00")
    assert "350.00" in candidates_s

def test_vectorized_validation():
    """Verify cumulative sum validation in pandas works correctly."""
    txs = [
        {"transaction_date": "01/06/2026", "debit_amount": "", "credit_amount": "", "running_balance": "1000.00"},
        {"transaction_date": "02/06/2026", "debit_amount": "", "credit_amount": "2500.00", "running_balance": "3500.00"},
        {"transaction_date": "03/06/2026", "debit_amount": "120.50", "credit_amount": "", "running_balance": "3379.50"}
    ]
    df, ok, flags = validate_statement(1000.00, 3379.50, txs)
    assert ok
    assert not flags
    assert (df["status"] == "clean").all()

def test_repair_and_triage_loop():
    """Verify that a corrupted statement is repaired and flagged transactions are triaged."""
    # Corrupted debit amount "12O.50" (capital letter O instead of zero)
    txs = [
        {"transaction_date": "01/06/2026", "debit_amount": "", "credit_amount": "", "running_balance": "1000.00"},
        {"transaction_date": "02/06/2026", "debit_amount": "", "credit_amount": "2500.00", "running_balance": "3500.00"},
        {"transaction_date": "03/06/2026", "debit_amount": "12O.50", "credit_amount": "", "running_balance": "3379.50"}
    ]
    
    triage_txs, repair_log, flags = repair_and_triage(1000.00, 3379.50, txs)
    
    # Assert repair output
    assert len(repair_log) == 1
    assert repair_log[0]["corrected_value"] == "120.50"
    assert triage_txs[2]["status"] == "auto_repaired"
    assert triage_txs[2]["repair_info"]["corrected_value"] == "120.50"

def test_anchor_field_row_grouping():
    """Verify that continuation lines without dates are correctly grouped into description."""
    headers = {
        "transaction_date": 0,
        "description": 1,
        "debit_amount": 2,
        "credit_amount": 3,
        "running_balance": 4
    }
    rows = [
        ["01/06/2026", "Grocery Shop Supermarket", "120.50", "", "3379.50"],
        ["", "Store #55", "", "", ""],
        ["02/06/2026", "Online Transfer", "300.00", "", "3079.50"]
    ]
    grouped = group_wrapped_rows(rows, headers)
    assert len(grouped) == 2
    assert grouped[0][1] == "Grocery Shop Supermarket Store #55"
    assert grouped[1][1] == "Online Transfer"

def test_split_headers_merge():
    """Verify columns with multi-row headers are concatenated correctly."""
    rows = [
        ["Transaction", "Description", "Withdrawals", "Deposits", "Running"],
        ["Date", "Narrative", "(Dr)", "(Cr)", "Balance"],
        ["01/06/2026", "Opening Balance", "", "", "1000.00"]
    ]
    headers, body = merge_split_headers(rows, 2)
    assert len(headers) == 5
    assert "Transaction Date" in headers[0]
    assert "Withdrawals (Dr)" in headers[2]
    assert len(body) == 1

def test_cell_traversal_recovery():
    """Verify cell-traversal deviation is truncated and recovered."""
    expected = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    
    # Generated has mismatch at index 4 (generated (1, 2) instead of (1, 1))
    generated = [
        (0, 0, "D1"), (0, 1, "D2"), (0, 2, "D3"),
        (1, 0, "D4"), (1, 2, "D5")
    ]
    
    reprompts = 0
    def reprompt_cb(prefix, next_coord):
        nonlocal reprompts
        reprompts += 1
        if next_coord == (1, 1):
            return [(1, 1, "D5_repaired"), (1, 2, "D6_repaired")]
        return []
        
    recovered = recover_cell_traversal(expected, generated, reprompt_cb)
    assert reprompts == 1
    assert len(recovered) == 6
    assert recovered[4] == (1, 1, "D5_repaired")
    assert recovered[5] == (1, 2, "D6_repaired")
