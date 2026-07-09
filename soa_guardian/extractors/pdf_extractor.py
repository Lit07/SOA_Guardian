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
                            
                # Heuristic: if pdfplumber extracted a very small table (e.g. < 8 rows)
                # but the page contains a large amount of text (e.g. > 100 words),
                # it's likely a borderless table with a small bordered footer (like aging analysis),
                # meaning the main transaction data was missed. Discard and use word-reconstruction.
                if page_grid:
                    words = page.extract_words()
                    if len(words) > 100 and len(page_grid) < 8:
                        page_grid = []
                        
                # Fallback: if no tables are detected (e.g. borderless), perform layout-aware word-coordinate reconstruction
                if not page_grid:
                    words = page.extract_words()
                    if words:
                        # Group words that share a similar vertical coordinate
                        rows_dict = {}
                        for w in words:
                            top_val = w["top"]
                            found = False
                            for row_top in rows_dict:
                                if abs(row_top - top_val) <= 4.0:
                                    rows_dict[row_top].append(w)
                                    found = True
                                    break
                            if not found:
                                rows_dict[top_val] = [w]
                                
                        # Sort rows vertically (top-to-bottom)
                        sorted_tops = sorted(rows_dict.keys())
                        
                        # Find the header row
                        header_top = None
                        best_match_count = 0
                        header_keywords = {"date", "doc", "txn", "type", "po", "debit", "credit", "balance", "amount", "particulars", "description", "ref"}
                        
                        for top in sorted_tops:
                            row_words = sorted(rows_dict[top], key=lambda x: x["x0"])
                            cells = []
                            curr_text = ""
                            prev_x1 = None
                            for w in row_words:
                                if prev_x1 is not None and (w["x0"] - prev_x1) > 15.0:
                                    cells.append(curr_text.strip())
                                    curr_text = w["text"]
                                else:
                                    curr_text += " " + w["text"] if curr_text else w["text"]
                                prev_x1 = w["x1"]
                            if curr_text:
                                cells.append(curr_text.strip())
                                
                            match_count = sum(1 for c in cells if any(kw in c.lower() for kw in header_keywords))
                            if match_count > best_match_count and match_count >= 3:
                                best_match_count = match_count
                                header_top = top
                                
                        if header_top is not None:
                            # Group header words into columns and get their coordinates
                            row_words = sorted(rows_dict[header_top], key=lambda x: x["x0"])
                            columns = []
                            curr_col = None
                            for w in row_words:
                                if curr_col is None:
                                    curr_col = {"x0": w["x0"], "x1": w["x1"], "words": [w]}
                                elif (w["x0"] - curr_col["x1"]) > 15.0:
                                    columns.append(curr_col)
                                    curr_col = {"x0": w["x0"], "x1": w["x1"], "words": [w]}
                                else:
                                    curr_col["x1"] = max(curr_col["x1"], w["x1"])
                                    curr_col["words"].append(w)
                            if curr_col:
                                columns.append(curr_col)
                                
                            for col in columns:
                                col["center"] = (col["x0"] + col["x1"]) / 2
                                
                            # Cache the columns template on self to allow reuse across pages
                            self._last_detected_columns = columns
                            
                        # If no header detected on this page, try to reuse the template from previous pages
                        active_columns = getattr(self, "_last_detected_columns", None)
                        
                        if active_columns:
                            for top in sorted_tops:
                                row_words = sorted(rows_dict[top], key=lambda x: x["x0"])
                                
                                # Group words in this row into logical cells based on small gaps
                                cells_in_row = []
                                curr_cell = None
                                for w in row_words:
                                    if curr_cell is None:
                                        curr_cell = {"x0": w["x0"], "x1": w["x1"], "text": w["text"]}
                                    elif (w["x0"] - curr_cell["x1"]) > 12.0:
                                        cells_in_row.append(curr_cell)
                                        curr_cell = {"x0": w["x0"], "x1": w["x1"], "text": w["text"]}
                                    else:
                                        curr_cell["x1"] = max(curr_cell["x1"], w["x1"])
                                        curr_cell["text"] += " " + w["text"]
                                if curr_cell:
                                    cells_in_row.append(curr_cell)
                                    
                                # Place each cell into the closest column
                                reconstructed_row = [""] * len(active_columns)
                                for cell in cells_in_row:
                                    cell_center = (cell["x0"] + cell["x1"]) / 2
                                    closest_col_idx = min(range(len(active_columns)), key=lambda i: abs(active_columns[i]["center"] - cell_center))
                                    if reconstructed_row[closest_col_idx]:
                                        reconstructed_row[closest_col_idx] += " " + cell["text"]
                                    else:
                                        reconstructed_row[closest_col_idx] = cell["text"]
                                        
                                if any(cell for cell in reconstructed_row):
                                    page_grid.append(reconstructed_row)
                        else:
                            # Fallback if no columns are available at all
                            for top in sorted_tops:
                                row_words = sorted(rows_dict[top], key=lambda x: x["x0"])
                                col_cells = []
                                current_cell_text = ""
                                prev_x1 = None
                                for w in row_words:
                                    if prev_x1 is not None and (w["x0"] - prev_x1) > 12.0:
                                        col_cells.append(current_cell_text.strip())
                                        current_cell_text = w["text"]
                                    else:
                                        current_cell_text += " " + w["text"] if current_cell_text else w["text"]
                                    prev_x1 = w["x1"]
                                if current_cell_text:
                                    col_cells.append(current_cell_text.strip())
                                    
                                if any(cell for cell in col_cells):
                                    page_grid.append(col_cells)
                                
                extracted_pages.append(page_grid)
                
        return extracted_pages
