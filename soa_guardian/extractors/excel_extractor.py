import os
import pandas as pd
from typing import List, Optional
from soa_guardian.extractors.base import BaseExtractor

class ExcelExtractor(BaseExtractor):
    """Table extractor for XLSX and CSV spreadsheet files."""
    
    def extract(self, file_path: str, page_indices: Optional[List[int]] = None) -> List[List[List[str]]]:
        _, ext = os.path.splitext(file_path.lower())
        
        # Determine format and read as raw string grids
        try:
            if ext == ".csv":
                import csv
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    grid_data = list(reader)
                df = pd.DataFrame(grid_data)
            else:
                # Read first sheet for Excel files
                df = pd.read_excel(file_path, header=None, dtype=str)
        except Exception as e:
            # Return empty page grid on read failures
            return [[]]
            
        # Fill NaN values with empty strings
        df = df.fillna("")
        
        # Clean and strip whitespaces from all cells
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            
        grid = df.values.tolist()
        
        # Filter out completely empty rows
        grid = [row for row in grid if any(cell for cell in row)]
        
        # Spreadsheet files are treated as a single page
        return [grid]
