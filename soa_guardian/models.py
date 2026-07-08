from pydantic import BaseModel, Field, computed_field
from typing import List, Optional, Dict, Any, Literal

class StatementMetadata(BaseModel):
    bank_name: str = Field(default="", description="Name of the bank")
    account_number: str = Field(default="", description="Account number")
    statement_start_date: str = Field(default="", description="Start date of the statement period")
    statement_end_date: str = Field(default="", description="End date of the statement period")
    detected_date_locale: str = Field(default="", description="Detected date formatting locale (e.g., DMY, MDY)")
    detected_numeric_locale: str = Field(default="", description="Detected numeric formatting locale (e.g., comma_decimal, period_decimal)")
    vendor_name: Optional[str] = Field(default=None, description="Name of the vendor")
    uen: Optional[str] = Field(default=None, description="UEN / GST Registration Number")
    customer_id: Optional[str] = Field(default=None, description="Customer Identifier")
    salesman_id: Optional[str] = Field(default=None, description="Salesman Identifier")
    term_code: Optional[str] = Field(default=None, description="Term Code")
    original_currency: str = Field(default="USD", description="Detected or configured statement currency")
    universal_currency: str = Field(default="USD", description="The target reporting currency")
    exchange_rate: float = Field(default=1.0, description="Conversion rate (1 original_currency = X universal_currency)")

class RepairInfo(BaseModel):
    raw_value: str = Field(description="The raw unparsed value before repair")
    corrected_value: str = Field(description="The repaired value")
    reason: str = Field(description="The reason/candidate that resolved the arithmetic equations")

class Transaction(BaseModel):
    transaction_date: str = Field(default="", description="Date of transaction")
    description: str = Field(default="", description="Transaction description/narrative")
    debit_amount: Optional[float] = Field(default=None, description="Debit amount (outgoing funds)")
    credit_amount: Optional[float] = Field(default=None, description="Credit amount (incoming funds)")
    running_balance: float = Field(default=0.0, description="Reported running balance")
    status: Literal["clean", "flagged", "auto_repaired", "escalated"] = Field(default="clean", description="Validation status")
    confidence: float = Field(default=1.0, description="Confidence of extraction/mapping")
    repair_info: Optional[RepairInfo] = Field(default=None, description="Details of auto-repair, only present if status is auto_repaired")
    additional_fields: Dict[str, str] = Field(default_factory=dict, description="Custom columns not mapped to canonical fields")
    universal_debit: Optional[float] = Field(default=None, description="Debit amount converted to universal currency")
    universal_credit: Optional[float] = Field(default=None, description="Credit amount converted to universal currency")
    universal_balance: Optional[float] = Field(default=None, description="Balance converted to universal currency")

class ClassificationVector(BaseModel):
    file_type: Literal["pdf", "xlsx", "csv", "unknown"] = Field(default="unknown")
    text_layer_present: bool = Field(default=False)
    layout_complexity: Literal["low", "medium", "high"] = Field(default="low")
    ocr_noise_level: Literal["low", "medium", "high"] = Field(default="low")
    garbage_value_ratio: float = Field(default=0.0)
    line_readable: bool = Field(default=True)
    table_border_type: Literal["bordered", "borderless", "implicit"] = Field(default="bordered")
    header_structure: Literal["single_row", "multi_row", "split_cell"] = Field(default="single_row")
    merged_cell_density: float = Field(default=0.0)
    language: Literal["single", "multilingual"] = Field(default="single")
    date_format_locale: Literal["DMY", "MDY", "ambiguous"] = Field(default="ambiguous")
    numeric_format_locale: Literal["comma_decimal", "period_decimal", "ambiguous"] = Field(default="ambiguous")
    page_role_estimate: Dict[str, str] = Field(default_factory=dict, description="Estimate role of each page")
    skew_or_rotation: bool = Field(default=False)
    page_count: int = Field(default=1)

class UnparsedLine(BaseModel):
    raw_text: str = Field(description="Raw text of the unparsed line")
    source_page: int = Field(description="Page number where the unparsed line occurred")
    reason: str = Field(description="Reason why the line was not parsed")
    review_required: bool = Field(default=True, description="Always true for unparsed lines")

class CanonicalStatement(BaseModel):
    statement_metadata: StatementMetadata = Field(default_factory=StatementMetadata)
    opening_balance: float = Field(default=0.0, description="Starting balance of statement")
    closing_balance: float = Field(default=0.0, description="Ending balance of statement")
    transactions: List[Transaction] = Field(default_factory=list, description="List of transactions")
    confidence: float = Field(default=1.0, description="Overall extraction confidence")
    extraction_method: str = Field(default="", description="Name of the extraction method/tool used")
    source_page: str = Field(default="", description="Pages where transactions were extracted")
    anomaly_flags: List[str] = Field(default_factory=list, description="Any detected schema or business rule anomalies")
    unparsed_lines: List[UnparsedLine] = Field(default_factory=list, description="Any lines that failed to parse completely")
    repair_log: List[Dict[str, Any]] = Field(default_factory=list, description="Auditing record of repair attempts and resolutions")
    original_headers: List[str] = Field(default_factory=list, description="Original list of header column names")
    header_mapping: Dict[str, int] = Field(default_factory=dict, description="Mapped column indices")
    output_format_columns: Dict[str, str] = Field(default_factory=dict, description="Mapped column headers for final output format")

    @computed_field
    @property
    def review_required(self) -> bool:
        """Returns True if any transaction status is escalated or if there are unparsed lines."""
        if any(tx.status == "escalated" for tx in self.transactions):
            return True
        if any(line.review_required for line in self.unparsed_lines):
            return True
        return False
