from soa_guardian.models import ClassificationVector

def plan_extraction(cv: ClassificationVector) -> str:
    """Option A (deterministic router) that maps a ClassificationVector to an extractor name.
    
    Adheres strictly to the routing specs in Section 11 of the specification.
    """
    if cv.text_layer_present and cv.table_border_type == "bordered" and cv.layout_complexity == "low":
        return "digital_text_simple_table"
        
    if cv.text_layer_present and cv.table_border_type == "borderless":
        return "digital_text_borderless_table"
        
    if not cv.text_layer_present and cv.merged_cell_density < 0.4 and cv.layout_complexity != "high":
        if cv.language == "single":
            return "scanned_single_language"
        else:
            return "scanned_multilingual"
            
    if cv.merged_cell_density > 0.4 or cv.header_structure == "split_cell" or cv.layout_complexity == "high":
        return "irregular_or_merged_cells"
        
    return "full_pipeline_fallback"

def should_run_retrieval(cv: ClassificationVector, threshold: int = 5) -> bool:
    """Routes page_count > threshold through the Page/Section Retrieval Stage (Section 5b)."""
    return cv.page_count > threshold
