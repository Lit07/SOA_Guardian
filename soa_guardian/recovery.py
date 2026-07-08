from typing import List, Tuple, Callable, Any

def merge_split_headers(rows: List[List[str]], num_header_rows: int = 2) -> Tuple[List[str], List[List[str]]]:
    """Identifies table headers split across the first N rows and merges them column-wise.
    
    Prevents duplicate words in the merged header text.
    
    Args:
        rows: The raw grid rows.
        num_header_rows: Number of top rows to treat as potential split headers.
        
    Returns:
        A tuple of (merged_headers, body_rows).
    """
    if not rows:
        return [], []
        
    # Determine the maximum column width across the header rows
    num_cols = max(len(r) for r in rows[:num_header_rows])
    
    # Initialize list for merged headers
    merged_headers = [""] * num_cols
    
    for r_idx in range(min(num_header_rows, len(rows))):
        row = rows[r_idx]
        for c_idx in range(num_cols):
            if c_idx < len(row):
                cell_val = row[c_idx].strip()
                if cell_val:
                    if merged_headers[c_idx]:
                        # Prevent duplicate adjacent words (e.g. "Amount" and "Amount")
                        if cell_val.lower() not in merged_headers[c_idx].lower():
                            merged_headers[c_idx] += " " + cell_val
                    else:
                        merged_headers[c_idx] = cell_val
                        
    return merged_headers, rows[num_header_rows:]

def recover_cell_traversal(
    expected_sequence: List[Tuple[int, int]],
    generated_sequence: List[Tuple[int, int, str]], # list of (row_idx, col_idx, value)
    re_prompt_callback: Callable[[List[Tuple[int, int, str]], Tuple[int, int]], List[Tuple[int, int, str]]],
    max_recovery_attempts: int = 3
) -> List[Tuple[int, int, str]]:
    """InstrucTE Cell-Traversal Error Recovery (Section 9).
    
    Compares the generated cell coordinate sequence against the expected grid coordinate sequence.
    On first deviation, truncates the sequence and re-prompts the callback with the prefix
    and the next expected target cell coordinate.
    """
    attempts = 0
    current_sequence = list(generated_sequence)
    
    while attempts < max_recovery_attempts:
        deviation_idx = -1
        
        # Check for first deviation against expected sequence
        for idx, expected_coord in enumerate(expected_sequence):
            if idx >= len(current_sequence):
                # Generated sequence is too short; deviation point is the next expected cell
                deviation_idx = idx
                break
                
            gen_coord = (current_sequence[idx][0], current_sequence[idx][1])
            if gen_coord != expected_coord:
                deviation_idx = idx
                break
                
        # If no deviation found, or we've validated the whole expected sequence, we're done
        if deviation_idx == -1 or deviation_idx >= len(expected_sequence):
            break
            
        attempts += 1
        
        # Truncate at deviation point
        truncated_prefix = current_sequence[:deviation_idx]
        next_expected_cell = expected_sequence[deviation_idx]
        
        # Call re-prompting callback to obtain corrected remainder
        resumed_suffix = re_prompt_callback(truncated_prefix, next_expected_cell)
        
        # Update current sequence and repeat validation
        current_sequence = truncated_prefix + resumed_suffix
        
    return current_sequence
