import warnings
import numpy as np
from typing import Dict, List, Tuple, Optional, Any

# Initial seed alias lists for canonical fields
SEED_ALIASES = {
    "transaction_date": ["date", "txn date", "value date", "post date", "trans date", "transaction date", "booking date"],
    "description": ["description", "particulars", "details", "narrative", "transaction details", "remarks", "memo"],
    "debit_amount": ["debit", "withdrawal", "dr", "paid out", "debit amount", "amount dr", "out", "payments"],
    "credit_amount": ["credit", "deposit", "cr", "received", "credit amount", "amount cr", "in", "receipts"],
    "running_balance": ["balance", "running balance", "running bal", "bal", "cumulative balance", "account balance"]
}

class SemanticMapper:
    """Retrieval-augmented semantic mapper for statement columns."""
    
    def __init__(self, use_embeddings: bool = True):
        self.aliases = {k: list(v) for k, v in SEED_ALIASES.items()}
        self.model = None
        self.anchor_embeddings = {}
        
        if use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                # Suppress download messages and warning logs
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self._compute_anchor_embeddings()
            except Exception as e:
                # Log fallbacks to dictionary mapping on import/load issues
                print(f"Warning: sentence-transformers not available, falling back to dictionary: {e}")
                self.model = None

    def _compute_anchor_embeddings(self):
        """Pre-compute embeddings for canonical seed aliases."""
        if not self.model:
            return
        for field, alias_list in self.aliases.items():
            embeddings = self.model.encode(alias_list, convert_to_numpy=True)
            self.anchor_embeddings[field] = embeddings

    def _compute_similarity(self, header: str) -> Dict[str, float]:
        """Compute cosine similarity of the header against each canonical field's aliases."""
        if not self.model or not self.anchor_embeddings:
            return {}
            
        header_emb = self.model.encode([header], convert_to_numpy=True)[0]
        header_norm = header_emb / (np.linalg.norm(header_emb) + 1e-9)
        
        similarities = {}
        for field, embeddings in self.anchor_embeddings.items():
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9
            normalized_embeddings = embeddings / norms
            sims = np.dot(normalized_embeddings, header_norm)
            # Use maximum similarity against all field aliases
            similarities[field] = float(np.max(sims))
            
        return similarities

    def _dictionary_match(self, header: str) -> Tuple[Optional[str], float]:
        """Check if the header matches any alias using simple text rules."""
        header_clean = header.lower().strip()
        
        # 1. Exact match check
        for field, alias_list in self.aliases.items():
            if header_clean in [a.lower() for a in alias_list]:
                return field, 1.0
                
        # 2. Substring match check
        for field, alias_list in self.aliases.items():
            for alias in alias_list:
                alias_clean = alias.lower()
                if len(header_clean) > 2 and len(alias_clean) > 2:
                    if alias_clean in header_clean or header_clean in alias_clean:
                        return field, 0.80
                        
        return None, 0.0

    def map_header(self, header: str, sample_values: Optional[List[str]] = None) -> Tuple[Optional[str], float]:
        """Maps a header string to a canonical field name."""
        header_clean = header.strip()
        if not header_clean:
            return None, 0.0
            
        # 1. Compute embedding-based similarity first if model is loaded
        if self.model:
            sims = self._compute_similarity(header_clean)
            if sims:
                best_field = max(sims, key=sims.get)
                best_score = sims[best_field]
                if best_score >= 0.85:
                    # Dynamically append to alias database to improve future matches
                    if header_clean not in self.aliases[best_field]:
                        self.aliases[best_field].append(header_clean)
                        self._compute_anchor_embeddings()
                    return best_field, best_score
                    
        # 2. Fall back to dictionary matching
        dict_field, dict_score = self._dictionary_match(header_clean)
        if dict_field:
            return dict_field, dict_score
            
        return None, 0.0

    def map_columns(self, headers: List[str], sample_rows: Optional[List[List[str]]] = None) -> Dict[str, int]:
        """Maps a list of table headers to canonical fields, returning canonical_field -> column_index."""
        mapping = {}
        for idx, header in enumerate(headers):
            samples = []
            if sample_rows:
                for row in sample_rows:
                    if idx < len(row):
                        samples.append(row[idx])
                        
            field, score = self.map_header(header, samples)
            if field and field not in mapping:
                mapping[field] = idx
                
        return mapping
