import re
from typing import List, Optional
from rank_bm25 import BM25Okapi

# Standard query keywords defined in the spec
QUERY_KEYWORDS = ["opening", "balance", "closing", "transaction", "debit", "credit"]

def tokenize_text(text: str) -> List[str]:
    """Tokenize text and add synthetic tokens for pattern matches (like dates)."""
    if not text:
        return []
        
    # Normalize and extract word tokens
    tokens = re.findall(r'\b\w+\b', text.lower())
    
    # Check for date patterns (e.g., DD/MM/YYYY, YYYY-MM-DD, DD-MMM-YYYY)
    # If found, add a special token "date_pattern_hit" to the document tokens
    date_patterns = [
        r'\b\d{2}[/\.-]\d{2}[/\.-]\d{4}\b',
        r'\b\d{4}[/\.-]\d{2}[/\.-]\d{2}\b',
        r'\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b', # e.g. 12 Jan 2026
        r'\b\d{2}[A-Za-z]{3}\d{2,4}\b',       # e.g. 12Jan26
    ]
    for pattern in date_patterns:
        if re.search(pattern, text):
            tokens.append("date_pattern_hit")
            
    return tokens

def preprocess_image_placeholder(image_bytes: bytes) -> bytes:
    """Preprocess image: segmentation, orientation detection, size normalization.
    
    Stub/Placeholder for scanned pages as specified in Section 5b.
    """
    return image_bytes

def retrieve_relevant_pages(
    pages_text: List[str], 
    threshold: float = 0.4,
    query_terms: Optional[List[str]] = None
) -> List[int]:
    """Perform rank_bm25 retrieval over a list of page texts to identify candidate transaction pages.
    
    Only triggered for multi-page documents (page_count > 5).
    
    Args:
        pages_text: List of raw string text for each page of the document.
        threshold: Relative score threshold (relative to maximum page score) to filter pages.
        query_terms: Optional query terms to override default keywords.
        
    Returns:
        List of 0-based page indices that are relevant to extraction.
    """
    if not pages_text:
        return []
        
    if query_terms is None:
        query_terms = list(QUERY_KEYWORDS)
        
    # Standard query tokenization: include keywords and "date_pattern_hit"
    query = [q.lower() for q in query_terms] + ["date_pattern_hit"]
    
    # Tokenize all pages
    corpus = [tokenize_text(page_text) for page_text in pages_text]
    
    # Initialize BM25Okapi
    bm25 = BM25Okapi(corpus)
    
    # Get scores for the query
    scores = bm25.get_scores(query)
    
    # If all scores are 0, return all pages as fallback
    max_score = max(scores) if len(scores) > 0 else 0
    if max_score <= 0.0:
        return list(range(len(pages_text)))
        
    # Return page indices where score is >= threshold * max_score
    relevant_indices = []
    for idx, score in enumerate(scores):
        if score >= threshold * max_score:
            relevant_indices.append(idx)
            
    return relevant_indices
