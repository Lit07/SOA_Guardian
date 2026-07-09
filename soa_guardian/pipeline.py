import re
import pdfplumber
from typing import List, Dict, Any, Tuple, Optional
from soa_guardian.models import (
    CanonicalStatement, StatementMetadata, Transaction, UnparsedLine, RepairInfo
)
from soa_guardian.profiler import profile_document
from soa_guardian.planner import plan_extraction, should_run_retrieval
from soa_guardian.retrieval import retrieve_relevant_pages
from soa_guardian.extractors import PDFExtractor, ExcelExtractor
from soa_guardian.grouping import group_wrapped_rows
from soa_guardian.mapping import SemanticMapper
from soa_guardian.recovery import merge_split_headers
from soa_guardian.validator import parse_currency, repair_and_triage
from soa_guardian.vendor_registry import VendorRegistry

def extract_metadata_and_balances(
    text_content: str,
    raw_pages: List[List[List[str]]],
    locale: str = "period_decimal"
) -> Tuple[float, float, str, str, str, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Scans the document pages/grids to extract metadata and balances."""
    opening_balance = 0.0
    closing_balance = 0.0
    bank_name = "Unknown Bank"
    account_number = ""
    start_date = ""
    end_date = ""
    uen = None
    customer_id = None
    salesman_id = None
    term_code = None
            
    # Simple bank name extraction
    for bank in ["Chase", "Citi", "Wells Fargo", "HSBC", "Barclays", "Apex Bank", "SoA Guardian Bank"]:
        if bank.lower() in text_content.lower():
            bank_name = bank
            break
            
    # Search for metadata in line-by-line whitespace-stripped format
    for line in text_content.split("\n"):
        line_clean = re.sub(r'\s+', '', line).upper()
        
        # Account number
        if not account_number:
            acc_match = re.search(r'ACC(?:OUNT)?(?:NUMBER|NO|#)?[:\-]?([A-Z0-9-]+)', line_clean)
            if acc_match:
                account_number = acc_match.group(1).strip()
                
        # Singapore UEN
        if not uen:
            uen_match = re.search(r'(?<!\d)(?:\d{8,9}[A-Z]|[TSR]\d{2}[A-Z]{2}\d{4}[A-Z])(?![A-Z0-9])', line_clean)
            if uen_match:
                uen = uen_match.group(0)
                
        # Customer ID
        if not customer_id:
            cust_match = re.search(r'CUST(?:OMER)?ID[:\-]?([A-Z0-9-]+)', line_clean)
            if cust_match:
                customer_id = cust_match.group(1).strip()
                
        # Salesman ID
        if not salesman_id:
            sales_match = re.search(r'SALESMANID[:\-]?([A-Z0-9-]+)', line_clean)
            if sales_match:
                salesman_id = sales_match.group(1).strip()
                
        # Term Code
        if not term_code:
            term_match = re.search(r'TERMCOD[E]?[:\-]?([A-Z0-9-]+)', line_clean)
            if term_match:
                term_code = term_match.group(1).strip()

    # 2. Extract opening/closing balances from grid structure
    op_patterns = ["opening balance", "balance brought forward", "prev balance", "start balance", "balance b/f"]
    cl_patterns = ["closing balance", "balance carried forward", "ending balance", "new balance", "balance c/f"]
    
    found_op = False
    found_cl = False
    
    for page in raw_pages:
        for row in page:
            row_str = " ".join(row).lower()
            
            # Opening balance check
            for pat in op_patterns:
                if pat in row_str and not found_op:
                    for cell in row:
                        val = parse_currency(cell, locale)
                        if val != 0.0 and pat not in cell.lower():
                            opening_balance = val
                            found_op = True
                            break
                            
            # Closing balance check
            for pat in cl_patterns:
                if pat in row_str and not found_cl:
                    for cell in row:
                        val = parse_currency(cell, locale)
                        if val != 0.0 and pat not in cell.lower():
                            closing_balance = val
                            found_cl = True
                            break
                            
    # Fallback to regex checks on raw text content
    if not found_op:
        op_match = re.search(r'(?:Opening\s+Balance|Prev\s+Balance|Balance\s+Forward|B/F)\s*[:\-\s]?\s*([0-9\.,\-]+)', text_content, re.IGNORECASE)
        if op_match:
            opening_balance = parse_currency(op_match.group(1), locale)
            found_op = True
            
    if not found_cl:
        cl_match = re.search(r'(?:Closing\s+Balance|Ending\s+Balance|C/F)\s*[:\-\s]?\s*([0-9\.,\-]+)', text_content, re.IGNORECASE)
        if cl_match:
            closing_balance = parse_currency(cl_match.group(1), locale)
            found_cl = True
            
    # Date boundary extraction (find first and last dates in the text)
    date_matches = re.findall(r'\b\d{1,2}[/\.-]\d{1,2}[/\.-]\d{2,4}\b|\b\d{4}[/\.-]\d{1,2}[/\.-]\d{1,2}\b', text_content)
    if len(date_matches) >= 2:
        start_date = date_matches[0]
        end_date = date_matches[-1]
        
    return opening_balance, closing_balance, bank_name, account_number, start_date, end_date, uen, customer_id, salesman_id, term_code, found_op, found_cl

def fuzzy_match_headers(h1: str, h2: str) -> bool:
    def normalize_header(h: str) -> str:
        s = h.lower().strip()
        s = re.sub(r'\bno\b|\bno\.\b|\bnum\b', 'number', s)
        return re.sub(r'[^a-z0-9]', '', s)
        
    c1 = normalize_header(h1)
    c2 = normalize_header(h2)
    if not c1 or not c2:
        return False
    if c1 == c2:
        return True
    if len(c1) >= 3 and c1 in c2:
        return True
    if len(c2) >= 3 and c2 in c1:
        return True
        
    short_map = {
        "doc": "document",
        "ref": "reference",
        "txn": "transaction",
        "trans": "transaction",
        "tran": "transaction",
        "amt": "amount",
        "bal": "balance",
        "desc": "description",
        "particular": "description"
    }
    for k, v in short_map.items():
        if (k in c1 and v in c2) or (k in c2 and v in c1):
            return True
    return False

from typing import Optional

def process_statement(
    file_path: str, 
    excel_output_path: Optional[str] = None,
    flat_table: bool = False,
    universal_currency: str = "USD",
    exchange_rate: float = 1.0,
    custom_mapping_path: Optional[str] = None
) -> CanonicalStatement:
    """Ties together all pipeline modules into the final processing call."""
    # 1. Profile document heuristics
    cv = profile_document(file_path)
    
    # 2. Extract extraction plan name
    extractor_name = plan_extraction(cv)
    
    # 3. Retrieve relevant page indices for multi-page PDF processing
    run_retrieval = should_run_retrieval(cv)
    page_indices = None
    
    if cv.file_type == "pdf":
        extractor = PDFExtractor()
        if run_retrieval:
            try:
                with pdfplumber.open(file_path) as pdf:
                    pages_text = [p.extract_text() or "" for p in pdf.pages]
                page_indices = retrieve_relevant_pages(pages_text)
            except Exception:
                page_indices = None
    else:
        extractor = ExcelExtractor()
        
    # Extract raw table grids
    raw_pages = extractor.extract(file_path, page_indices)
    
    # Set numeric format locale
    locale = cv.numeric_format_locale
    if locale == "ambiguous":
        locale = "period_decimal" # Default fallback
        
    # 4. Extract full text layer from all pages to search for metadata and balances (covers cover/summary pages)
    text_content = ""
    if cv.file_type == "pdf":
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text_content += (page.extract_text() or "") + "\n"
        except Exception:
            pass
            
    # Fallback to combining raw page grids (for XLSX, CSV, or failed PDF text extraction)
    if not text_content:
        for page in raw_pages:
            for row in page:
                text_content += " ".join(row) + "\n"
                
    # Extract opening/closing balances and metadata
    opening_balance, closing_balance, bank_name, account_number, start_date, end_date, uen, customer_id, salesman_id, term_code, found_op, found_cl = extract_metadata_and_balances(
        text_content, raw_pages, locale
    )
    
    mapper = SemanticMapper(use_embeddings=True)
    registry = VendorRegistry(mappings_path=custom_mapping_path)
    
    # 5. Pre-check vendor by text aliases in text layer
    vendor_match = registry.identify_vendor(text_content, [])
    vendor_config = None
    vendor_name = None
    if vendor_match:
        vendor_key, vendor_config = vendor_match
        vendor_name = vendor_config.get("official_name")
        bank_name = vendor_config.get("official_name", bank_name)
        if "numeric_locale" in vendor_config:
            locale = vendor_config["numeric_locale"]
    else:
        # Fallback: use first line of text
        lines = [l.strip() for l in text_content.split("\n") if l.strip()]
        if lines:
            vendor_name = lines[0]
            
    # Resolve currency from vendor_config or text heuristics
    original_currency = "USD"
    if vendor_config and "currency" in vendor_config:
        original_currency = vendor_config["currency"]
    else:
        text_lower = text_content.lower()
        if "sgd" in text_lower or "singapore dollar" in text_lower or "s$" in text_lower:
            original_currency = "SGD"
        elif "eur" in text_lower or "euro" in text_lower or "€" in text_lower:
            original_currency = "EUR"
        elif "gbp" in text_lower or "sterling" in text_lower or "£" in text_lower:
            original_currency = "GBP"
        elif "myr" in text_lower or "ringgit" in text_lower:
            original_currency = "MYR"
        elif "usd" in text_lower or "us dollar" in text_lower or "us$" in text_lower:
            original_currency = "USD"

    # Determine exchange rate
    if universal_currency == original_currency:
        actual_exchange_rate = 1.0
    else:
        actual_exchange_rate = exchange_rate
        if actual_exchange_rate == 1.0 and vendor_config and "exchange_rate" in vendor_config:
            try:
                actual_exchange_rate = float(vendor_config["exchange_rate"])
            except (ValueError, TypeError):
                actual_exchange_rate = 1.0
            
    all_extracted_txs = []
    unparsed_lines = []
    
    header_mapping = {}
    header_found = False
    original_headers_list = []
    
    # 6. Process pages and recover row structures
    for page_idx, page_grid in enumerate(raw_pages):
        actual_page_num = page_indices[page_idx] + 1 if page_indices else page_idx + 1
        start_row_idx = 0
        
        # Locate table header
        if not header_found:
            for r_idx, row in enumerate(page_grid):
                row_clean = [cell.strip() for cell in row]
                
                # Check if we already identified the vendor by text aliases
                if vendor_config:
                    vendor_cols = vendor_config["columns"]
                    mapping = {}
                    for field, v_header in vendor_cols.items():
                        for c_idx, cell in enumerate(row_clean):
                            if fuzzy_match_headers(cell, v_header):
                                mapping[field] = c_idx
                                break
                    if "transaction_date" in mapping and ("description" in mapping or any(f in mapping for f in ["debit_amount", "credit_amount", "running_balance"])):
                        if "description" not in mapping:
                            for idx in range(len(row_clean)):
                                if idx not in mapping.values():
                                    mapping["description"] = idx
                                    break
                        header_mapping = mapping
                        header_found = True
                        start_row_idx = r_idx + 1
                else:
                    # Fallback: scan all registered vendors to see if this row matches their header names
                    matched_vendor_key = None
                    matched_mapping = {}
                    best_match_count = 0
                    for key, config in registry.vendors.items():
                        mapping = {}
                        for field, v_header in config["columns"].items():
                            for c_idx, cell in enumerate(row_clean):
                                if fuzzy_match_headers(cell, v_header):
                                    mapping[field] = c_idx
                                    break
                        if "transaction_date" in mapping:
                            actual_match_count = len(mapping)
                            min_required = max(3, len(config["columns"]) - 1) if len(config["columns"]) >= 3 else len(config["columns"])
                            if actual_match_count >= min_required:
                                if "description" not in mapping:
                                    for idx in range(len(row_clean)):
                                        if idx not in mapping.values():
                                            mapping["description"] = idx
                                            break
                                match_count = len(mapping)
                                if match_count > best_match_count:
                                    best_match_count = match_count
                                    matched_vendor_key = key
                                    matched_mapping = mapping
                                
                    if matched_vendor_key:
                        vendor_key = matched_vendor_key
                        vendor_config = registry.vendors[vendor_key]
                        header_mapping = matched_mapping
                        header_found = True
                        start_row_idx = r_idx + 1
                        bank_name = vendor_config.get("official_name", bank_name)
                        if "numeric_locale" in vendor_config:
                            locale = vendor_config["numeric_locale"]
                            
                # Fallback: check standard semantic mapping (for unregistered vendors)
                if not header_found:
                    mapping = mapper.map_columns(row)
                    has_date = "transaction_date" in mapping
                    has_desc = "description" in mapping
                    has_financial = any(f in mapping for f in ["debit_amount", "credit_amount", "running_balance"])
                    if has_date and (has_desc or has_financial):
                        if not has_desc:
                            for idx in range(len(row)):
                                if idx not in mapping.values():
                                    mapping["description"] = idx
                                    break
                        header_mapping = mapping
                        header_found = True
                        start_row_idx = r_idx + 1
                    elif (has_date or has_desc) and r_idx + 1 < len(page_grid):
                        # Try lookahead merge of split headers to see if it yields both fields
                        next_row = page_grid[r_idx + 1]
                        merged_temp, _ = merge_split_headers([row, next_row], num_header_rows=2)
                        mapping_merged = mapper.map_columns(merged_temp)
                        has_date_m = "transaction_date" in mapping_merged
                        has_desc_m = "description" in mapping_merged
                        has_fin_m = any(f in mapping_merged for f in ["debit_amount", "credit_amount", "running_balance"])
                        if has_date_m and (has_desc_m or has_fin_m):
                            if not has_desc_m:
                                for idx in range(len(merged_temp)):
                                    if idx not in mapping_merged.values():
                                        mapping_merged["description"] = idx
                                        break
                            header_mapping = mapping_merged
                            header_found = True
                            start_row_idx = r_idx + 2
                        
                # Look ahead check for split headers if header was found just now
                if header_found:
                    if r_idx + 1 < len(page_grid):
                        next_row = page_grid[r_idx + 1]
                        date_idx = header_mapping.get("transaction_date")
                        has_date_value = False
                        if date_idx is not None and date_idx < len(next_row):
                            from soa_guardian.grouping import is_valid_anchor
                            has_date_value = is_valid_anchor(next_row[date_idx], "transaction_date")
                            
                        # If next row doesn't have a date but has non-empty text, merge split headers
                        if not has_date_value and any(cell.strip() for cell in next_row):
                            merged_headers, _ = merge_split_headers(page_grid[r_idx:r_idx+2], num_header_rows=2)
                            if vendor_config:
                                mapping = {}
                                for field, v_header in vendor_config["columns"].items():
                                    for c_idx, cell in enumerate(merged_headers):
                                        if cell.strip().lower() == v_header.lower() or v_header.lower() in cell.strip().lower():
                                            mapping[field] = c_idx
                                            break
                                header_mapping = mapping
                            else:
                                header_mapping = mapper.map_columns(merged_headers)
                            start_row_idx = r_idx + 2
                    
                    if start_row_idx == r_idx + 2:
                        merged, _ = merge_split_headers(page_grid[r_idx:r_idx+2], num_header_rows=2)
                        original_headers_list = [cell.strip() for cell in merged]
                    else:
                        original_headers_list = [cell.strip() for cell in page_grid[r_idx]]
                    break
                    
        if not header_found:
            # Header not yet located: log non-empty rows as unparsed lines
            for row in page_grid:
                row_str = " ".join(row).strip()
                if row_str:
                    unparsed_lines.append(UnparsedLine(
                        raw_text=row_str,
                        source_page=actual_page_num,
                        reason="No table header identified yet",
                        review_required=True
                    ))
            continue
            
        # Segment body rows
        body_rows = page_grid[start_row_idx:]
        cleaned_body_rows = []
        for row in body_rows:
            row_str = " ".join(row).strip()
            if not row_str:
                continue
            # Filter footer / balance lines out of transaction set
            is_footer = False
            if any(k in row_str.lower() for k in ["closing balance", "brought forward", "carried forward"]):
                is_footer = True
            elif re.search(r'\bpage\s+\d+\b|\bpage\s+\d+\s+of\s+\d+\b', row_str.lower()):
                is_footer = True
                
            if is_footer:
                continue
            cleaned_body_rows.append(row)
            
        # Group wrapped rows
        grouped_body_rows = group_wrapped_rows(cleaned_body_rows, header_mapping)
        
        # Convert grouped rows to transaction dictionaries
        for row in grouped_body_rows:
            date_idx = header_mapping["transaction_date"]
            if date_idx >= len(row):
                continue
            date_val = row[date_idx].strip()
            
            if not date_val:
                row_str = " ".join(row).strip()
                unparsed_lines.append(UnparsedLine(
                    raw_text=row_str,
                    source_page=actual_page_num,
                    reason="Transaction row missing date field",
                    review_required=True
                ))
                continue
                
            # Populate fields
            desc_val = row[header_mapping["description"]].strip() if ("description" in header_mapping and header_mapping["description"] < len(row)) else ""
            debit_val = row[header_mapping["debit_amount"]].strip() if ("debit_amount" in header_mapping and header_mapping["debit_amount"] < len(row)) else "0.0"
            credit_val = row[header_mapping["credit_amount"]].strip() if ("credit_amount" in header_mapping and header_mapping["credit_amount"] < len(row)) else "0.0"
            bal_val = row[header_mapping["running_balance"]].strip() if ("running_balance" in header_mapping and header_mapping["running_balance"] < len(row)) else "0.0"
            
            # Extract additional fields (all columns not mapped to canonical fields)
            mapped_indices = {v for k, v in header_mapping.items() if v is not None}
            additional_fields = {
                str(idx): row[idx].strip() 
                for idx in range(len(row))
                if idx not in mapped_indices
            }
            
            all_extracted_txs.append({
                "transaction_date": date_val,
                "description": desc_val,
                "debit_amount": debit_val,
                "credit_amount": credit_val,
                "running_balance": bal_val,
                "status": "clean",
                "confidence": 1.0,
                "repair_info": None,
                "additional_fields": additional_fields
            })
            
    # 6. Run Vectorized validation, repair, and triage
    final_txs, repair_log, final_flags = repair_and_triage(
        opening_balance, closing_balance, all_extracted_txs, locale
    )
    
    # Instantiate Pydantic classes
    transactions_objs = []
    for tx in final_txs:
        repair_info_obj = None
        if tx.get("repair_info"):
            repair_info_obj = RepairInfo(
                raw_value=tx["repair_info"]["raw_value"],
                corrected_value=tx["repair_info"]["corrected_value"],
                reason=tx["repair_info"]["reason"]
            )
            
        # Parse debits and credits correctly as optional float models
        deb = parse_currency(tx["debit_amount"], locale) if tx.get("debit_amount") else None
        cred = parse_currency(tx["credit_amount"], locale) if tx.get("credit_amount") else None
        
        # If amounts are zero and not explicitly defined, let's treat them cleanly
        if deb == 0.0 and (not tx.get("debit_amount") or tx.get("debit_amount") in ["0.0", "0", ""]):
            deb = None
        if cred == 0.0 and (not tx.get("credit_amount") or tx.get("credit_amount") in ["0.0", "0", ""]):
            cred = None
            
        tx_bal = parse_currency(tx["running_balance"], locale)
        u_deb = round(deb * actual_exchange_rate, 2) if deb is not None else None
        u_cred = round(cred * actual_exchange_rate, 2) if cred is not None else None
        u_bal = round(tx_bal * actual_exchange_rate, 2)
            
        transactions_objs.append(Transaction(
            transaction_date=tx["transaction_date"],
            description=tx["description"],
            debit_amount=deb,
            credit_amount=cred,
            running_balance=tx_bal,
            status=tx["status"],
            confidence=tx["confidence"],
            repair_info=repair_info_obj,
            additional_fields=tx.get("additional_fields", {}),
            universal_debit=u_deb,
            universal_credit=u_cred,
            universal_balance=u_bal
        ))
        
    source_pages_str = ",".join(str(i+1) for i in page_indices) if page_indices else "1"
    
    # Metadata assembly
    metadata = StatementMetadata(
        bank_name=bank_name,
        account_number=account_number,
        statement_start_date=start_date,
        statement_end_date=end_date,
        detected_date_locale="DMY",
        detected_numeric_locale=locale,
        vendor_name=vendor_name,
        uen=uen,
        customer_id=customer_id,
        salesman_id=salesman_id,
        term_code=term_code,
        original_currency=original_currency,
        universal_currency=universal_currency,
        exchange_rate=actual_exchange_rate
    )
    
    overall_confidence = 1.0
    if transactions_objs:
        overall_confidence = sum(tx.confidence for tx in transactions_objs) / len(transactions_objs)
    if not found_op:
        final_flags.append("Opening balance boundary extraction failed: using default 0.0")
    if not found_cl:
        final_flags.append("Closing balance boundary extraction failed: using default 0.0")
    if not found_op or not found_cl:
        overall_confidence = min(overall_confidence, 0.70)
        
    canonical = CanonicalStatement(
        statement_metadata=metadata,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        transactions=transactions_objs,
        confidence=overall_confidence,
        extraction_method=extractor_name,
        source_page=source_pages_str,
        anomaly_flags=final_flags,
        unparsed_lines=unparsed_lines,
        repair_log=repair_log,
        original_headers=original_headers_list,
        header_mapping=header_mapping or {},
        output_format_columns=vendor_config.get("output_format_columns", {}) if vendor_config else {}
    )
    
    if excel_output_path:
        from soa_guardian.exporter import export_to_excel
        column_headers = None
        if vendor_config and "columns" in vendor_config:
            cols = vendor_config["columns"]
            column_headers = [
                cols.get("transaction_date", "Date"),
                cols.get("description", "Description"),
                cols.get("debit_amount", "Debit"),
                cols.get("credit_amount", "Credit"),
                cols.get("running_balance", "Balance")
            ]
        export_to_excel(
            canonical, 
            excel_output_path, 
            flat_table=flat_table, 
            column_headers=column_headers
        )
        
    return canonical

