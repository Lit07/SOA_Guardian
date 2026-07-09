import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_FILE = "soa_guardian.db"
# Place database in project root
DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBStatement(Base):
    __tablename__ = "statements"
    
    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String, default="")
    account_number = Column(String, default="")
    statement_start_date = Column(String, default="")
    statement_end_date = Column(String, default="")
    vendor_name = Column(String, nullable=True)
    uen = Column(String, nullable=True)
    customer_id = Column(String, nullable=True)
    salesman_id = Column(String, nullable=True)
    term_code = Column(String, nullable=True)
    
    original_currency = Column(String, default="USD")
    universal_currency = Column(String, default="USD")
    exchange_rate = Column(Float, default=1.0)
    
    opening_balance = Column(Float, default=0.0)
    closing_balance = Column(Float, default=0.0)
    confidence = Column(Float, default=1.0)
    extraction_method = Column(String, default="")
    source_page = Column(String, default="")
    review_required = Column(Boolean, default=False)
    
    anomaly_flags_json = Column(Text, default="[]")  # Serialized list
    file_path = Column(String, default="")
    created_date = Column(DateTime, default=datetime.utcnow)
    template_file_path = Column(String, nullable=True)
    mapping_file_path = Column(String, nullable=True)
    output_format_headers_json = Column(Text, default="{}")
    original_headers_json = Column(Text, default="[]")
    header_mapping_json = Column(Text, default="{}")
    
    transactions = relationship("DBTransaction", back_populates="statement", cascade="all, delete-orphan")
    audit_logs = relationship("DBAuditLog", back_populates="statement", cascade="all, delete-orphan")

    @property
    def anomaly_flags(self):
        try:
            return json.loads(self.anomaly_flags_json)
        except Exception:
            return []

    @anomaly_flags.setter
    def anomaly_flags(self, value):
        self.anomaly_flags_json = json.dumps(value)

    @property
    def original_headers(self):
        try:
            return json.loads(self.original_headers_json)
        except Exception:
            return []

    @original_headers.setter
    def original_headers(self, value):
        self.original_headers_json = json.dumps(value)

    @property
    def header_mapping(self):
        try:
            return json.loads(self.header_mapping_json)
        except Exception:
            return {}

    @header_mapping.setter
    def header_mapping(self, value):
        self.header_mapping_json = json.dumps(value)

    @property
    def output_format_columns(self):
        try:
            return json.loads(self.output_format_headers_json)
        except Exception:
            return {}

    @output_format_columns.setter
    def output_format_columns(self, value):
        self.output_format_headers_json = json.dumps(value)

class DBTransaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=False)
    
    transaction_date = Column(String, default="")
    description = Column(String, default="")
    debit_amount = Column(Float, nullable=True)
    credit_amount = Column(Float, nullable=True)
    running_balance = Column(Float, default=0.0)
    status = Column(String, default="clean")  # clean, auto_repaired, flagged, escalated
    confidence = Column(Float, default=1.0)
    
    repair_info_json = Column(Text, nullable=True)  # Serialized Dict
    additional_fields_json = Column(Text, default="{}")  # Serialized Dict
    
    universal_debit = Column(Float, nullable=True)
    universal_credit = Column(Float, nullable=True)
    universal_balance = Column(Float, nullable=True)
    
    statement = relationship("DBStatement", back_populates="transactions")

    @property
    def repair_info(self):
        if not self.repair_info_json:
            return None
        try:
            return json.loads(self.repair_info_json)
        except Exception:
            return None

    @repair_info.setter
    def repair_info(self, value):
        self.repair_info_json = json.dumps(value) if value else None

    @property
    def additional_fields(self):
        try:
            return json.loads(self.additional_fields_json)
        except Exception:
            return {}

    @additional_fields.setter
    def additional_fields(self, value):
        self.additional_fields_json = json.dumps(value)

class DBAuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id"), nullable=False)
    
    log_type = Column(String, default="repair_attempt")  # repair_attempt or unparsed_line
    raw_text = Column(String, default="")
    corrected_value = Column(String, nullable=True)
    reason = Column(String, default="")
    field_location = Column(String, nullable=True)
    source_page = Column(Integer, nullable=True)
    
    statement = relationship("DBStatement", back_populates="audit_logs")

def init_db():
    Base.metadata.create_all(bind=engine)
    # SQLite schema migrations check
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            cursor = conn.execute(text("PRAGMA table_info(statements)"))
            cols = [row[1] for row in cursor.fetchall()]
            if "template_file_path" not in cols:
                conn.execute(text("ALTER TABLE statements ADD COLUMN template_file_path TEXT"))
            if "mapping_file_path" not in cols:
                conn.execute(text("ALTER TABLE statements ADD COLUMN mapping_file_path TEXT"))
            if "output_format_headers_json" not in cols:
                conn.execute(text("ALTER TABLE statements ADD COLUMN output_format_headers_json TEXT"))
    except Exception as e:
        print(f"Warning: db migration failed: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
