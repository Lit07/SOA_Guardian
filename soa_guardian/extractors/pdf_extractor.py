import pdfplumber
from typing import List, Optional
from soa_guardian.extractors.base import BaseExtractor

class PDFExtractor(BaseExtractor):
    """Layout-aware table extractor for digital text PDFs using pdfplumber."""
    
    def extract(self, file_path: str, page_indices: Optional[List[int]] = None) -> List[List[List[str]]]:
        extracted_pages = []
        
        with pdfplumber.open(file_path) as pdf:
            pages_to_process = range(len(pdf.pages)) if page_indices is None else page_indices
            
            for idx in pages_to_process:
                if idx >= len(pdf.pages):
                    continue
                page = pdf.pages[idx]
                
                # Attempt to extract table using pdfplumber's default grid detector
                tables = page.extract_tables()
                page_grid = []
                
                if tables:
                    for table in tables:
                        for row in table:
                            clean_row = [str(cell).strip() if cell is not None else "" for cell in row]
                            page_grid.append(clean_row)
                            
                # Fallback: if no tables are detected (e.g. borderless), perform word-coordinate reconstruction
                if not page_grid:
                    words = page.extract_words()
                    if words:
                        # Group words that share a similar vertical coordinate
                        rows_dict = {}
                        for w in words:
                            top_val = w["top"]
                            found = False
                            for row_top in rows_dict:
                                # Tolerate minor vertical deviations up to 4pt (font sizes and baselines)
                                if abs(row_top - top_val) <= 4.0:
                                    rows_dict[row_top].append(w)
                                    found = True
                                    break
                            if not found:
                                rows_dict[top_val] = [w]
                                
                        # Sort rows vertically (top-to-bottom)
                        sorted_tops = sorted(rows_dict.keys())
                        for top in sorted_tops:
                            row_words = rows_dict[top]
                            # Sort words horizontally (left-to-right)
                            sorted_row_words = sorted(row_words, key=lambda x: x["x0"])
                            
                            # Segment words into columns based on horizontal gaps (threshold = 12pt)
                            col_cells = []
                            current_cell_text = ""
                            prev_x1 = None
                            
                            for w in sorted_row_words:
                                if prev_x1 is not None and (w["x0"] - prev_x1) > 12.0:
                                    col_cells.append(current_cell_text.strip())
                                    current_cell_text = w["text"]
                                else:
                                    if current_cell_text:
                                        current_cell_text += " " + w["text"]
                                    else:
                                        current_cell_text = w["text"]
                                prev_x1 = w["x1"]
                                
                            if current_cell_text:
                                col_cells.append(current_cell_text.strip())
                                
                            # Only add non-empty rows
                            if any(cell for cell in col_cells):
                                page_grid.append(col_cells)
                                
                extracted_pages.append(page_grid)
                
        return extracted_pages
