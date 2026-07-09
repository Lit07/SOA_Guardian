import re
import warnings
import numpy as np
from typing import Dict, List, Tuple, Optional, Any

# Initial seed alias lists for canonical fields
SEED_ALIASES = {
    "transaction_date": ["date", "txn date", "value date", "post date", "trans date", "tran date", "transaction date", "booking date", "doc date", "invoice date", "posting date", "payment date", "billing date", "bill date"],
    "description": ["description", "particulars", "details", "narrative", "transaction details", "remarks", "remark", "memo", "text", "assignment", "reference", "reference key", "document no", "document number", "invoice no", "invoice number", "doc no", "doc number"],
    "debit_amount": ["debit", "withdrawal", "dr", "paid out", "debit amount", "amount dr", "payments"],
    "credit_amount": ["credit", "deposit", "cr", "received", "credit amount", "amount cr", "receipts"],
    "running_balance": ["balance", "running balance", "running bal", "bal", "cumulative balance", "account balance", "cum bal", "cum balance"]
}

def normalize_header_text(header: str) -> str:
    if not header:
        return ""
    text = str(header).strip().lower()
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def infer_header_field(header: str) -> Optional[str]:
    normalized = normalize_header_text(header)
    if not normalized:
        return None

    words = set(normalized.split())

    # Helper to check if any token matches as a whole word or multi-word phrase
    def has_phrase(phrase: str) -> bool:
        if " " in phrase:
            return phrase in normalized
        return phrase in words

    if any(has_phrase(t) for t in ["transaction date", "doc date", "posting date", "value date", "payment date", "book date", "date", "posting", "txn", "trans", "tran", "value", "booking", "payment"]):
        return "transaction_date"

    if any(has_phrase(t) for t in ["closing balance", "running balance", "cum bal", "cum balance", "balance", "outstanding", "bal"]):
        return "running_balance"

    if any(has_phrase(t) for t in ["credit", "deposit", "cr", "receipt", "received", "refund"]):
        return "credit_amount"

    if any(has_phrase(t) for t in ["debit", "withdrawal", "dr", "payment", "paid"]):
        return "debit_amount"

    if any(has_phrase(t) for t in ["description", "particular", "detail", "narrative", "remark", "memo", "text", "assignment", "reference", "invoice", "document", "type", "key", "number", "no", "doc"]):
        return "description"

    return None

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

        # 1. Exact match check first (highest confidence)
        dict_field, dict_score = self._dictionary_match(header_clean)
        if dict_field and dict_score == 1.0:
            return dict_field, 1.0

        # 2. Compute embedding-based similarity if model is loaded
        if self.model:
            sims = self._compute_similarity(header_clean)
            if sims:
                best_field = max(sims, key=sims.get)
                best_score = sims[best_field]
                if best_score >= 0.75:
                    return best_field, best_score

        # 3. Fall back to inferred rules
        inferred = infer_header_field(header_clean)
        if inferred:
            return inferred, 0.80

        # 4. Fall back to dictionary substring matches
        if dict_field:
            return dict_field, dict_score

        return None, 0.0

    def map_columns(self, headers: List[str], sample_rows: Optional[List[List[str]]] = None) -> Dict[str, int]:
        """Maps a list of table headers to canonical fields using global bipartite matching."""
        candidates = []
        for idx, header in enumerate(headers):
            header_clean = header.strip()
            if not header_clean:
                continue
                
            samples = []
            if sample_rows:
                for row in sample_rows:
                    if idx < len(row):
                        samples.append(row[idx])
                        
            # Compute score for all canonical fields
            similarities = {}
            dict_field, dict_score = self._dictionary_match(header_clean)
            if dict_field and dict_score == 1.0:
                similarities[dict_field] = 1.0
            else:
                if self.model:
                    sims = self._compute_similarity(header_clean)
                    for f, s in sims.items():
                        similarities[f] = max(similarities.get(f, 0.0), s)
                inferred = infer_header_field(header_clean)
                if inferred:
                    similarities[inferred] = max(similarities.get(inferred, 0.0), 0.85)
                    
            for field, score in similarities.items():
                if score >= 0.70:
                    candidates.append((score, field, idx))
                    
        # Sort candidates by score descending to assign highest confidence pairs first
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        mapping = {}
        assigned_cols = set()
        assigned_fields = set()
        
        for score, field, col_idx in candidates:
            if field not in assigned_fields and col_idx not in assigned_cols:
                mapping[field] = col_idx
                assigned_fields.add(field)
                assigned_cols.add(col_idx)
                
        return mapping
