import re
from typing import List, Dict, Optional

# Regex matching common date formats (e.g. DD/MM/YYYY, DD-MMM-YY, YYYY/MM/DD)
DATE_REGEX = re.compile(
    r'('
    r'\b\d{1,2}[/\.-]\d{1,2}[/\.-]\d{2,4}\b|'
    r'\b\d{4}[/\.-]\d{1,2}[/\.-]\d{1,2}\b|'
    r'\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|'
    r'\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}\b'
    r')'
)

def is_valid_anchor(val: str, col_type: str) -> bool:
    """Determine if a cell value contains a valid anchor (e.g. matches date format)."""
    val = val.strip()
    if not val:
        return False
    if col_type == "transaction_date":
        return bool(DATE_REGEX.search(val))
    return True

def choose_anchor_column(rows: List[List[str]], header_mapping: Dict[str, int]) -> Optional[int]:
    """Select the best anchor column from header mapping.
    
    Prefers transaction_date, otherwise returns first column index.
    """
    if "transaction_date" in header_mapping:
        return header_mapping["transaction_date"]
    
    if not header_mapping:
        return None
        
    best_col = None
    max_non_empty = -1
    for col_name, col_idx in header_mapping.items():
        non_empty_count = sum(1 for r in rows if col_idx < len(r) and r[col_idx].strip())
        if non_empty_count > max_non_empty:
            max_non_empty = non_empty_count
            best_col = col_idx
            
    return best_col

def is_transaction_row(row: List[str], header_mapping: Dict[str, int]) -> bool:
    """Checks if the row contains numerical transaction amounts in debit, credit, or running balance columns."""
    for field in ["debit_amount", "credit_amount", "running_balance"]:
        col_idx = header_mapping.get(field)
        if col_idx is not None and col_idx < len(row):
            val = row[col_idx].strip()
            if val:
                # Clean value and check if it is a number
                cleaned = re.sub(r'[^\d\.,\-]', '', val)
                if cleaned:
                    if cleaned.count(".") > 1 or cleaned.count("-") > 1:
                        continue
                    try:
                        float(cleaned.replace(",", ""))
                        return True
                    except ValueError:
                        pass
    return False

def group_wrapped_rows(
    rows: List[List[str]], 
    header_mapping: Dict[str, int]
) -> List[List[str]]:
    """Handles wrapped/continuation rows by grouping them under anchor-field records.
    
    - Operates on row-lists.
    - Any row lacking a valid anchor value (e.g., date) gets its text merged into
      the preceding logical record's description cell.
    - If a row lacks an anchor date but contains numeric values in amount columns,
      it is processed as a separate transaction row (carrying the date forward).
    """
    anchor_col_idx = choose_anchor_column(rows, header_mapping)
    if anchor_col_idx is None:
        return rows
        
    desc_col_idx = header_mapping.get("description")
    
    grouped_rows = []
    current_logical_row = None
    
    max_mapping_idx = max(header_mapping.values())
    
    for row in rows:
        # Pad row if too short
        if len(row) <= max_mapping_idx:
            row = row + [""] * (max_mapping_idx - len(row) + 1)
            
        anchor_val = row[anchor_col_idx].strip()
        is_new_record = is_valid_anchor(
            anchor_val, 
            "transaction_date" if anchor_col_idx == header_mapping.get("transaction_date") else "other"
        )
        
        # If it has a date, or if it is a transaction row lacking a date
        if is_new_record or is_transaction_row(row, header_mapping):
            if current_logical_row is not None:
                grouped_rows.append(current_logical_row)
            
            current_logical_row = list(row)
            
            # Carry forward date if empty
            date_col_idx = header_mapping.get("transaction_date")
            if date_col_idx is not None and date_col_idx < len(current_logical_row):
                if not current_logical_row[date_col_idx].strip() and grouped_rows:
                    prev_date = grouped_rows[-1][date_col_idx]
                    current_logical_row[date_col_idx] = prev_date
        else:
            # Continuation row
            if current_logical_row is not None:
                # Merge description text
                if desc_col_idx is not None and desc_col_idx < len(row):
                    cont_desc = row[desc_col_idx].strip()
                    if cont_desc:
                        if current_logical_row[desc_col_idx]:
                            current_logical_row[desc_col_idx] += " " + cont_desc
                        else:
                            current_logical_row[desc_col_idx] = cont_desc
                
                # Append values in other columns if logical row lacks them
                for idx, cell in enumerate(row):
                    if idx != anchor_col_idx and idx != desc_col_idx and idx < len(current_logical_row):
                        cell_val = cell.strip()
                        if cell_val and not current_logical_row[idx].strip():
                            current_logical_row[idx] = cell_val
            else:
                # If no logical row yet, keep row as-is (e.g. metadata or header row)
                grouped_rows.append(row)
                
    if current_logical_row is not None:
        grouped_rows.append(current_logical_row)
        
    return grouped_rows
