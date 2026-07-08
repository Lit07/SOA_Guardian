import os
import json
from typing import List, Dict, Any, Optional, Tuple

class VendorRegistry:
    """Intelligent database registry to auto-identify vendor profiles in unnamed files."""
    
    def __init__(self, mappings_path: Optional[str] = None):
        self.vendors = {}
        if mappings_path is not None and mappings_path.lower().endswith(".xlsx"):
            if os.path.exists(mappings_path):
                excel_mappings = self._discover_excel_mappings(specific_path=mappings_path)
                if excel_mappings:
                    self.vendors.update(excel_mappings)
            return

        if mappings_path is None:
            # Auto-locate mappings file inside package root
            current_dir = os.path.dirname(os.path.abspath(__file__))
            mappings_path = os.path.join(current_dir, "vendor_mappings.json")
            
        if os.path.exists(mappings_path):
            try:
                with open(mappings_path, "r", encoding="utf-8") as f:
                    self.vendors = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load vendor_mappings.json: {e}")

        # Auto-discover and parse external Excel mapping sheet if present
        excel_mappings = self._discover_excel_mappings()
        if excel_mappings:
            self.vendors.update(excel_mappings)

    def _discover_excel_mappings(self, specific_path: Optional[str] = None) -> Dict[str, Any]:
        """Scans workspace directories or loads specific path to parse Excel mappings registry."""
        import glob
        import openpyxl
        import re
        
        if specific_path and os.path.exists(specific_path):
            paths = [specific_path]
        else:
            package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            search_paths = [
                package_root,
                os.path.join(package_root, "tests"),
                os.path.join(package_root, "scratch"),
                os.getcwd(),
                os.path.join(os.getcwd(), "tests"),
                os.path.join(os.getcwd(), "scratch")
            ]
            
            # Deduplicate paths
            unique_paths = []
            for p in search_paths:
                if p and os.path.exists(p):
                    abs_p = os.path.abspath(p)
                    if abs_p not in unique_paths:
                        unique_paths.append(abs_p)
            
            paths = []
            for base_path in unique_paths:
                paths.extend(glob.glob(os.path.join(base_path, "*.xlsx")))
                
        for path in paths:
            try:
                wb = openpyxl.load_workbook(path, read_only=True, keep_links=False)
                if "Final_mappings" in wb.sheetnames:
                    # Found the mappings file! Let's load the data
                    wb_full = openpyxl.load_workbook(path, data_only=True)
                    ws = wb_full["Final_mappings"]
                    
                    # 1. Read first row headers dynamically
                    first_row = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
                    vendors_idx = -1
                    for idx, h in enumerate(first_row):
                        if h and str(h).strip().lower() == "vendors":
                            vendors_idx = idx
                            break
                    if vendors_idx == -1:
                        vendors_idx = 0
                        
                    # Extract all target column headers
                    target_headers = []
                    target_header_indices = []
                    for idx, h in enumerate(first_row):
                        if idx != vendors_idx and h:
                            target_headers.append(str(h).strip())
                            target_header_indices.append(idx)
                            
                    excel_vendors = {}
                    # 2. Iterate rows and extract dynamically mapped fields
                    for row_idx in range(2, ws.max_row + 1):
                        vendor_val = ws.cell(row=row_idx, column=vendors_idx + 1).value
                        if not vendor_val:
                            continue
                        
                        vendor_name = str(vendor_val).strip()
                        vendor_key = re.sub(r'[^a-z0-9_]', '', re.sub(r'\s+', '_', re.sub(r'\.(xlsx|xls|pdf|csv)', '', vendor_name, flags=re.IGNORECASE)).lower())
                        
                        alias_name = re.sub(r'\.(xlsx|xls|pdf|csv)', '', vendor_name, flags=re.IGNORECASE).strip()
                        
                        mapping = {
                            "official_name": alias_name,
                            "aliases": [alias_name, alias_name.lower(), vendor_name],
                            "columns": {},
                            "output_format_columns": {}
                        }
                        
                        # Populate target mappings dynamically
                        for h_name, h_idx in zip(target_headers, target_header_indices):
                            cell_val = ws.cell(row=row_idx, column=h_idx + 1).value
                            mapping["output_format_columns"][h_name] = str(cell_val).strip() if cell_val else ""
                            
                        # Resolve standard canonical fields using fuzzy column name heuristics
                        date_h = next((h for h in target_headers if "date" in h.lower()), None)
                        desc_h = next((h for h in target_headers if "invoice" in h.lower() or "desc" in h.lower() or "particular" in h.lower()), None)
                        amt_h = next((h for h in target_headers if "amount" in h.lower() or "sum" in h.lower() or "val" in h.lower()), None)
                        
                        if date_h and mapping["output_format_columns"].get(date_h):
                            mapping["columns"]["transaction_date"] = mapping["output_format_columns"][date_h]
                        if desc_h and mapping["output_format_columns"].get(desc_h):
                            mapping["columns"]["description"] = mapping["output_format_columns"][desc_h]
                        if amt_h and mapping["output_format_columns"].get(amt_h):
                            mapping["columns"]["debit_amount"] = mapping["output_format_columns"][amt_h]
                            mapping["columns"]["credit_amount"] = mapping["output_format_columns"][amt_h]
                            
                        excel_vendors[vendor_key] = mapping
                    return excel_vendors
            except Exception as e:
                print(f"Warning: Discover Excel mappings error on {path}: {e}")
        return {}

    def identify_vendor(
        self, 
        text_content: str, 
        extracted_headers: List[str],
        similarity_threshold: float = 0.80
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Identifies vendor by scanning text for aliases, falling back to header structure matching.
        
        Args:
            text_content: Full text layer extracted from statement document.
            extracted_headers: List of raw header columns extracted from table.
            similarity_threshold: Overlap ratio threshold for structural matches (default 80%).
            
        Returns:
            Tuple of (vendor_key, vendor_config) if resolved, else None.
        """
        # Pass 1: Search for aliases in the raw text content
        text_lower = text_content.lower()
        for key, config in self.vendors.items():
            for alias in config.get("aliases", []):
                if alias.lower() in text_lower:
                    return key, config
                    
        # Pass 2: Fuzzy header structure overlap
        best_key = None
        best_score = 0.0
        
        cleaned_extracted = [h.strip().lower() for h in extracted_headers if h.strip()]
        
        if cleaned_extracted:
            for key, config in self.vendors.items():
                vendor_headers = [h.strip().lower() for h in config.get("columns", {}).values()]
                if not vendor_headers:
                    continue
                    
                matches = 0
                for vh in vendor_headers:
                    # Treat as matched if exact match or substring overlaps are found
                    if any(vh in eh or eh in vh for eh in cleaned_extracted):
                        matches += 1
                        
                score = matches / len(vendor_headers)
                if score > best_score:
                    best_score = score
                    best_key = key
                    
            if best_score >= similarity_threshold and best_key:
                return best_key, self.vendors[best_key]
                
        return None
