from abc import ABC, abstractmethod
from typing import List, Optional

class BaseExtractor(ABC):
    """Abstract base class for all SoA table extractors."""
    
    @abstractmethod
    def extract(self, file_path: str, page_indices: Optional[List[int]] = None) -> List[List[List[str]]]:
        """Extracts table grids from the document.
        
        Args:
            file_path: Path to the target document.
            page_indices: Optional list of page indices to restrict extraction to (0-indexed).
            
        Returns:
            A list representing the document pages. Each page contains a list of rows,
            and each row is a list of column cell string values.
            e.g., [ [ ["Header1", "Header2"], ["Val1", "Val2"] ] ]
        """
        pass
