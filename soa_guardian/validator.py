import re
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Any, Optional

def parse_currency(val: Any, locale: str = "period_decimal") -> float:
    """Robust currency parser respecting the detected locale."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
        
    s = str(val).strip()
    if not s:
        return 0.0
        
    # Exclude strings with forward slashes (common date formats like DD/MM/YYYY)
    if "/" in s:
        return 0.0
        
    # Exclude strings with more than one hyphen (common date formats like YYYY-MM-DD)
    if s.count("-") > 1:
        return 0.0
        
    # Exclude strings with multiple dots/commas when they act as date separators (e.g. DD.MM.YYYY)
    if locale == "period_decimal" and s.count(".") > 1:
        return 0.0
    if locale == "comma_decimal" and s.count(",") > 1:
        return 0.0
        
    # Check parenthetical negative formatting (e.g. (1,020.98) or ($120.50))
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
        
    # Remove currency signs and common layout characters, keeping negative sign and decimal/thousands separators
    s = re.sub(r'[^\d\.,-]', '', s)
    if not s:
        return 0.0
        
    if locale == "comma_decimal":
        # comma is decimal point (e.g. 1.234,56 or 1234,56)
        s = s.replace(".", "") # Remove thousands separator
        s = s.replace(",", ".") # Replace decimal comma with period
    else:
        # period is decimal point (e.g. 1,234.56 or 1234.56)
        s = s.replace(",", "") # Remove thousands separator
        
    try:
        parsed_val = float(s)
        if is_negative:
            # If it was in parentheses, make sure it is negative
            return -abs(parsed_val)
        return parsed_val
    except ValueError:
        return 0.0

def generate_candidates(raw_str: str) -> List[str]:
    """Generates confusable OCR and transposition digit candidates for repair."""
    candidates = []
    raw_str_clean = raw_str.strip()
    
    # 1. OCR confusable replacements (character -> digit)
    replacements = {
        'o': '0', 'O': '0',
        'I': '1', 'l': '1', 'i': '1',
        'S': '5', 's': '5',
        'B': '8', 'g': '9', 'z': '2', 'Z': '2'
    }
    
    chars = list(raw_str_clean)
    for i, c in enumerate(chars):
        if c in replacements:
            new_chars = list(chars)
            new_chars[i] = replacements[c]
            candidates.append("".join(new_chars))
            
    # 2. Transposition of adjacent digits
    for i in range(len(chars) - 1):
        if chars[i].isdigit() and chars[i+1].isdigit() and chars[i] != chars[i+1]:
            new_chars = list(chars)
            new_chars[i], new_chars[i+1] = new_chars[i+1], new_chars[i]
            candidates.append("".join(new_chars))
            
    # 3. Misplaced decimal point (shifting period)
    digits_only = re.sub(r'[^\d]', '', raw_str_clean)
    if digits_only:
        for dot_pos in range(1, min(4, len(digits_only))):
            candidates.append(digits_only[:-dot_pos] + "." + digits_only[-dot_pos:])
            
    # Deduplicate and validate candidates parse as float
    final_candidates = []
    for c in candidates:
        if c != raw_str_clean and c not in final_candidates:
            try:
                # Clean candidate and try float conversion
                clean_c = re.sub(r'[^\d\.-]', '', c)
                float(clean_c)
                final_candidates.append(c)
            except ValueError:
                pass
                
    return final_candidates

def detect_sign_convention(
    opening_balance: float,
    closing_balance: float,
    df: pd.DataFrame
) -> Tuple[float, float]:
    """Dynamically detects (credit_multiplier, debit_multiplier) from statement sequence math.
    
    Scores candidates based on both local sequence matches and overall global balance reconciliation.
    """
    if len(df) == 0:
        return 1.0, -1.0
        
    conventions = [
        (1.0, -1.0),  # Config A: Balance = Prev + Credit - Debit (Bank Statement default)
        (-1.0, 1.0),  # Config B: Balance = Prev - Credit + Debit (Vendor AP/Customer AR debtor layout)
        (1.0, 1.0),   # Config C: Balance = Prev + Credit + Debit (Signed columns/general ledgers)
        (-1.0, -1.0), # Config D: Balance = Prev - Credit - Debit
    ]
    
    test_len = min(10, len(df))
    prev_balances = df["balance_val"].shift(1).fillna(opening_balance).iloc[:test_len].values
    credits = df["credit_val"].iloc[:test_len].values
    debits = df["debit_val"].iloc[:test_len].values
    actual_balances = df["balance_val"].iloc[:test_len].values
    
    total_credits = df["credit_val"].sum()
    total_debits = df["debit_val"].sum()
    
    best_conv = (1.0, -1.0)
    max_score = -1
    
    for c_mult, d_mult in conventions:
        local_matches = 0
        for i in range(test_len):
            expected = prev_balances[i] + c_mult * credits[i] + d_mult * debits[i]
            if np.isclose(actual_balances[i], expected, atol=0.01):
                local_matches += 1
                
        # Global balance check across the entire statement
        expected_final = opening_balance + c_mult * total_credits + d_mult * total_debits
        global_match = np.isclose(expected_final, closing_balance, atol=0.01)
        
        # Massive score weight for global match to resolve low-variation sample locking
        score = local_matches
        if global_match:
            score += 100
            
        if score > max_score:
            max_score = score
            best_conv = (c_mult, d_mult)
            
    return best_conv

def validate_statement(
    opening_balance: float,
    closing_balance: float,
    transactions: List[Dict[str, Any]],
    locale: str = "period_decimal"
) -> Tuple[pd.DataFrame, bool, List[str]]:
    """Runs a vectorized running balance check using cumulative sums in Pandas.
    
    Dynamically adapts to the statement's sign convention configuration.
    """
    if not transactions:
        balance_match = np.isclose(opening_balance, closing_balance, atol=0.01)
        df = pd.DataFrame(columns=["debit_val", "credit_val", "balance_val", "expected_running", "status"])
        return df, balance_match, [] if balance_match else ["Opening and closing balance mismatch"]
        
    df = pd.DataFrame(transactions)
    
    # Pad columns if missing
    for col in ["debit_amount", "credit_amount", "running_balance"]:
        if col not in df.columns:
            df[col] = 0.0
            
    # Parse as float using locale
    df["debit_val"] = df["debit_amount"].apply(lambda x: parse_currency(x, locale))
    df["credit_val"] = df["credit_amount"].apply(lambda x: parse_currency(x, locale))
    df["balance_val"] = df["running_balance"].apply(lambda x: parse_currency(x, locale))
    
    # Detect the statement's active sign convention configuration
    c_mult, d_mult = detect_sign_convention(opening_balance, closing_balance, df)
    
    # Vectorized Cumulative balance check using detected sign multipliers
    df["expected_running"] = opening_balance + (c_mult * df["credit_val"].cumsum() + d_mult * df["debit_val"].cumsum())
    
    # Flag rows failing the close balance equality check
    df["status"] = np.where(
        np.isclose(df["balance_val"], df["expected_running"], atol=0.01),
        "clean", "flagged"
    )
    
    # Check overall equation
    last_expected = df["expected_running"].iloc[-1]
    overall_ok = np.isclose(last_expected, closing_balance, atol=0.01)
    
    anomaly_flags = []
    if not overall_ok:
        anomaly_flags.append(f"Closing balance mismatch: expected {last_expected:.2f}, got {closing_balance:.2f}")
        
    return df, overall_ok, anomaly_flags

def repair_and_triage(
    opening_balance: float,
    closing_balance: float,
    transactions: List[Dict[str, Any]],
    locale: str = "period_decimal"
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Performs up to 2 repair loop iterations targeting only the flagged subset of transactions.
    
    Also sets transaction-level triage flags and builds the repair log.
    """
    repair_log = []
    current_txs = [dict(tx) for tx in transactions]
    
    for iteration in range(2):
        # 1. Run vectorized validation to identify status
        df, overall_ok, flags = validate_statement(opening_balance, closing_balance, current_txs, locale)
        
        # Find flagged rows
        flagged_mask = df["status"] == "flagged"
        flagged_indices = df[flagged_mask].index.tolist()
        
        if not flagged_indices:
            # Statement is clean
            break
            
        # 2. Localize the break using secondary row-by-row validator adapting to detected signs
        c_mult, d_mult = detect_sign_convention(opening_balance, closing_balance, df)
        df["prev_balance"] = df["balance_val"].shift(1).fillna(opening_balance)
        df["expected_step"] = df["prev_balance"] + c_mult * df["credit_val"] + d_mult * df["debit_val"]
        df["step_ok"] = np.isclose(df["balance_val"], df["expected_step"], atol=0.01)
        
        broken_indices = df[~df["step_ok"]].index.tolist()
        # Target the first row where the running balance sequence breaks
        target_row_idx = broken_indices[0] if broken_indices else flagged_indices[0]
        
        row_data = current_txs[target_row_idx]
        fields_to_repair = ["debit_amount", "credit_amount", "running_balance"]
        repaired = False
        
        for field in fields_to_repair:
            raw_val = str(row_data.get(field, ""))
            if not raw_val or raw_val.lower() == "none" or raw_val == "0.0":
                continue
                
            candidates = generate_candidates(raw_val)
            for cand in candidates:
                # Test substitution
                test_txs = [dict(tx) for tx in current_txs]
                test_txs[target_row_idx][field] = cand
                
                # Check if substitution resolves the statement
                test_df, test_ok, test_flags = validate_statement(opening_balance, closing_balance, test_txs, locale)
                
                if test_ok:
                    current_txs = test_txs
                    repair_entry = {
                        "field": f"transactions[{target_row_idx}].{field}",
                        "raw_value": raw_val,
                        "corrected_value": cand,
                        "reason": f"OCR confusion repair resolved equations in iteration {iteration + 1}",
                        "confidence": 0.85
                    }
                    repair_log.append(repair_entry)
                    
                    # Update transaction attributes
                    current_txs[target_row_idx]["status"] = "auto_repaired"
                    current_txs[target_row_idx]["repair_info"] = {
                        "raw_value": raw_val,
                        "corrected_value": cand,
                        "reason": repair_entry["reason"]
                    }
                    current_txs[target_row_idx]["confidence"] = 0.85
                    repaired = True
                    break
            if repaired:
                break
                
        if not repaired:
            # Mismatch cannot be resolved automatically, stop repair loop
            break
            
    # Final validation pass to assign triage statuses
    df, overall_ok, final_flags = validate_statement(opening_balance, closing_balance, current_txs, locale)
    
    triage_txs = []
    for idx, row in df.iterrows():
        tx = dict(current_txs[idx])
        
        # Retain existing auto_repaired status
        if tx.get("status") == "auto_repaired":
            triage_txs.append(tx)
            continue
            
        # Assign triage tier
        mapping_confidence = tx.get("confidence", 1.0)
        if row["status"] == "clean":
            tx["status"] = "clean"
            tx["repair_info"] = None
        else:
            tx["status"] = "escalated"
            tx["repair_info"] = None
            tx["confidence"] = 0.50 # Degrade confidence on escalation
            
        triage_txs.append(tx)
        
    return triage_txs, repair_log, final_flags

def triage_transaction(status: str, confidence: float) -> str:
    """Triage helper mapping states to tiers (Section 10b)."""
    if status == "clean" and confidence >= 0.85:
        return "tier_0_accept"
    if status == "clean" and confidence < 0.85:
        return "tier_1_accept_flagged"
    if status == "auto_repaired":
        return "tier_2_auto_repair"
    return "tier_3_escalate"

def handle_unparseable_line(raw_text: str, source_page: int, reason: str) -> Dict[str, Any]:
    """Helper to structure unparseable statement lines for human triage."""
    return {
        "raw_text": raw_text,
        "source_page": source_page,
        "reason": reason,
        "review_required": True
    }
