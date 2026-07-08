import os
import pdfplumber
from soa_guardian.models import ClassificationVector

def profile_document(file_path: str) -> ClassificationVector:
    """Profiles a document based on cheap metadata heuristics (Phase 1)."""
    _, ext = os.path.splitext(file_path.lower())
    cv = ClassificationVector()
    
    if ext == ".pdf":
        cv.file_type = "pdf"
        try:
            with pdfplumber.open(file_path) as pdf:
                cv.page_count = len(pdf.pages)
                # Check if there is any text in the first page
                first_page = pdf.pages[0]
                text = first_page.extract_text() or ""
                cv.text_layer_present = len(text.strip()) > 0
                
                # Check if pdfplumber detects explicit tables/lines on the first page
                tables = first_page.find_tables()
                if tables:
                    cv.layout_complexity = "medium"
                    cv.table_border_type = "bordered"
                else:
                    cv.table_border_type = "borderless"
                    cv.layout_complexity = "medium"
                
                # Page role estimation: assume cover page for page 1 if multi-page
                cv.page_role_estimate = {
                    f"page_{i+1}": "transaction_table" if i > 0 else "cover"
                    for i in range(len(pdf.pages))
                }
                if len(pdf.pages) == 1:
                    cv.page_role_estimate["page_1"] = "transaction_table"
        except Exception:
            cv.text_layer_present = False
            cv.ocr_noise_level = "high"
            cv.layout_complexity = "high"
            cv.table_border_type = "implicit"
            
    elif ext in [".xlsx", ".xls"]:
        cv.file_type = "xlsx"
        cv.text_layer_present = True
        cv.table_border_type = "bordered"
        cv.layout_complexity = "low"
        cv.page_count = 1
        cv.page_role_estimate = {"page_1": "transaction_table"}
        
    elif ext == ".csv":
        cv.file_type = "csv"
        cv.text_layer_present = True
        cv.table_border_type = "borderless"
        cv.layout_complexity = "low"
        cv.page_count = 1
        cv.page_role_estimate = {"page_1": "transaction_table"}
        
    else:
        cv.file_type = "unknown"
        cv.text_layer_present = False
        cv.layout_complexity = "high"
        
    return cv
