import os
import shutil
import json
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from soa_guardian.pipeline import process_statement
from soa_guardian.web.db import init_db, get_db, DBStatement, DBTransaction, DBAuditLog
from soa_guardian.validator import repair_and_triage, parse_currency, validate_statement
from soa_guardian.models import CanonicalStatement, StatementMetadata, Transaction, RepairInfo, UnparsedLine
from soa_guardian.exporter import export_to_excel

# Create FastAPI app
app = FastAPI(title="SoA Guardian Dashboard API")

# Setup directories
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Initialize database schema on startup
init_db()

@app.post("/api/upload")
async def upload_statement(
    file: UploadFile = File(...),
    mapping_file: Optional[UploadFile] = File(None),
    template_file: Optional[UploadFile] = File(None),
    universal_currency: str = Form("USD"),
    exchange_rate: float = Form(1.0),
    flat_table: bool = Form(False),
    db: Session = Depends(get_db)
):
    # Save uploaded files
    file_ext = os.path.splitext(file.filename)[1]
    temp_file_name = f"stmt_{os.urandom(4).hex()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, temp_file_name)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    mapping_file_path = None
    if mapping_file and mapping_file.filename:
        map_ext = os.path.splitext(mapping_file.filename)[1]
        map_name = f"map_{os.urandom(4).hex()}{map_ext}"
        mapping_file_path = os.path.join(UPLOAD_DIR, map_name)
        with open(mapping_file_path, "wb") as buffer:
            shutil.copyfileobj(mapping_file.file, buffer)
            
    template_file_path = None
    if template_file and template_file.filename:
        tpl_ext = os.path.splitext(template_file.filename)[1]
        tpl_name = f"tpl_{os.urandom(4).hex()}{tpl_ext}"
        template_file_path = os.path.join(UPLOAD_DIR, tpl_name)
        with open(template_file_path, "wb") as buffer:
            shutil.copyfileobj(template_file.file, buffer)
        
    try:
        # Run core parsing pipeline
        canonical = process_statement(
            file_path=file_path,
            universal_currency=universal_currency,
            exchange_rate=exchange_rate,
            flat_table=flat_table,
            custom_mapping_path=mapping_file_path
        )
        
        # Resolve dynamic header mappings
        output_format_cols = canonical.output_format_columns
        if not output_format_cols:
            output_format_cols = {
                "Date": "transaction_date",
                "Description": "description",
                "Debit": "debit_amount",
                "Credit": "credit_amount",
                "Balance": "running_balance"
            }
            if canonical.statement_metadata.exchange_rate != 1.0:
                univ_cur = canonical.statement_metadata.universal_currency
                output_format_cols[f"Universal Debit ({univ_cur})"] = "universal_debit"
                output_format_cols[f"Universal Credit ({univ_cur})"] = "universal_credit"
                output_format_cols[f"Universal Balance ({univ_cur})"] = "universal_balance"
                
        # Save Statement record to SQLite
        db_stmt = DBStatement(
            bank_name=canonical.statement_metadata.bank_name,
            account_number=canonical.statement_metadata.account_number,
            statement_start_date=canonical.statement_metadata.statement_start_date,
            statement_end_date=canonical.statement_metadata.statement_end_date,
            vendor_name=canonical.statement_metadata.vendor_name,
            uen=canonical.statement_metadata.uen,
            customer_id=canonical.statement_metadata.customer_id,
            salesman_id=canonical.statement_metadata.salesman_id,
            term_code=canonical.statement_metadata.term_code,
            original_currency=canonical.statement_metadata.original_currency,
            universal_currency=canonical.statement_metadata.universal_currency,
            exchange_rate=canonical.statement_metadata.exchange_rate,
            opening_balance=canonical.opening_balance,
            closing_balance=canonical.closing_balance,
            confidence=canonical.confidence,
            extraction_method=canonical.extraction_method,
            source_page=canonical.source_page,
            review_required=canonical.review_required,
            file_path=file_path,
            template_file_path=template_file_path,
            mapping_file_path=mapping_file_path,
            output_format_headers_json=json.dumps(output_format_cols)
        )
        db_stmt.anomaly_flags = canonical.anomaly_flags
        
        db.add(db_stmt)
        db.commit()
        db.refresh(db_stmt)
        
        # Save Transaction records to SQLite
        for tx in canonical.transactions:
            db_tx = DBTransaction(
                statement_id=db_stmt.id,
                transaction_date=tx.transaction_date,
                description=tx.description,
                debit_amount=tx.debit_amount,
                credit_amount=tx.credit_amount,
                running_balance=tx.running_balance,
                status=tx.status,
                confidence=tx.confidence,
                universal_debit=tx.universal_debit,
                universal_credit=tx.universal_credit,
                universal_balance=tx.universal_balance
            )
            db_tx.additional_fields = tx.additional_fields
            if tx.repair_info:
                db_tx.repair_info = {
                    "raw_value": tx.repair_info.raw_value,
                    "corrected_value": tx.repair_info.corrected_value,
                    "reason": tx.repair_info.reason
                }
            db.add(db_tx)
            
        # Save Audit logs
        for entry in canonical.repair_log:
            db_log = DBAuditLog(
                statement_id=db_stmt.id,
                log_type="repair_attempt",
                field_location=entry.get("field", ""),
                raw_text=entry.get("raw_value", ""),
                corrected_value=entry.get("corrected_value", ""),
                reason=entry.get("reason", ""),
                confidence=entry.get("confidence", 1.0)
            )
            db.add(db_log)
            
        for line in canonical.unparsed_lines:
            db_log = DBAuditLog(
                statement_id=db_stmt.id,
                log_type="unparsed_line",
                raw_text=line.raw_text,
                source_page=line.source_page,
                reason=line.reason
            )
            db.add(db_log)
            
        db.commit()
        
        return {
            "success": True,
            "statement_id": db_stmt.id,
            "bank_name": db_stmt.bank_name,
            "vendor_name": db_stmt.vendor_name,
            "review_required": db_stmt.review_required,
            "confidence": db_stmt.confidence,
            "anomaly_flags": db_stmt.anomaly_flags
        }
    except Exception as e:
        # Clean up file on failure
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Pipeline processing failed: {str(e)}")

@app.post("/api/upload-registry")
async def upload_registry(file: UploadFile = File(...)):
    # Save custom registry spreadsheet directly into project root workspace
    target_path = "Final_mappings.xlsx"
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"success": True, "message": "Vendor mappings sheet uploaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mappings upload failed: {str(e)}")

@app.get("/api/statements")
async def list_statements(db: Session = Depends(get_db)):
    statements = db.query(DBStatement).order_by(DBStatement.created_date.desc()).all()
    return [
        {
            "id": s.id,
            "bank_name": s.bank_name,
            "account_number": s.account_number,
            "vendor_name": s.vendor_name,
            "statement_start_date": s.statement_start_date,
            "statement_end_date": s.statement_end_date,
            "review_required": s.review_required,
            "confidence": s.confidence,
            "created_date": s.created_date.isoformat() if s.created_date else None,
            "original_currency": s.original_currency,
            "universal_currency": s.universal_currency
        }
        for s in statements
    ]

@app.get("/api/statements/{id}")
async def get_statement_details(id: int, db: Session = Depends(get_db)):
    stmt = db.query(DBStatement).filter(DBStatement.id == id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
        
    transactions = db.query(DBTransaction).filter(DBTransaction.statement_id == id).order_by(DBTransaction.id).all()
    audit_logs = db.query(DBAuditLog).filter(DBAuditLog.statement_id == id).all()
    
    return {
        "statement": {
            "id": stmt.id,
            "bank_name": stmt.bank_name,
            "account_number": stmt.account_number,
            "statement_start_date": stmt.statement_start_date,
            "statement_end_date": stmt.statement_end_date,
            "vendor_name": stmt.vendor_name,
            "uen": stmt.uen,
            "customer_id": stmt.customer_id,
            "salesman_id": stmt.salesman_id,
            "term_code": stmt.term_code,
            "opening_balance": stmt.opening_balance,
            "closing_balance": stmt.closing_balance,
            "confidence": stmt.confidence,
            "review_required": stmt.review_required,
            "anomaly_flags": stmt.anomaly_flags,
            "original_currency": stmt.original_currency,
            "universal_currency": stmt.universal_currency,
            "exchange_rate": stmt.exchange_rate,
            "extraction_method": stmt.extraction_method,
            "source_page": stmt.source_page,
            "output_format_headers": json.loads(stmt.output_format_headers_json or "{}")
        },
        "transactions": [
            {
                "id": t.id,
                "transaction_date": t.transaction_date,
                "description": t.description,
                "debit_amount": t.debit_amount,
                "credit_amount": t.credit_amount,
                "running_balance": t.running_balance,
                "status": t.status,
                "confidence": t.confidence,
                "repair_info": t.repair_info,
                "additional_fields": t.additional_fields,
                "universal_debit": t.universal_debit,
                "universal_credit": t.universal_credit,
                "universal_balance": t.universal_balance
            }
            for t in transactions
        ],
        "audit_logs": [
            {
                "id": log.id,
                "log_type": log.log_type,
                "field_location": log.field_location,
                "raw_text": log.raw_text,
                "corrected_value": log.corrected_value,
                "reason": log.reason,
                "source_page": log.source_page
            }
            for log in audit_logs
        ]
    }

@app.post("/api/transactions/{id}/update")
async def update_transaction(
    id: int,
    data: dict,  # Expecting: {"transaction_date": "", "description": "", "debit_amount": float/str, "credit_amount": float/str, "running_balance": float/str}
    db: Session = Depends(get_db)
):
    tx = db.query(DBTransaction).filter(DBTransaction.id == id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
        
    stmt = db.query(DBStatement).filter(DBStatement.id == tx.statement_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Parent statement not found")
        
    # Update current row fields
    if "transaction_date" in data:
        tx.transaction_date = data["transaction_date"]
    if "description" in data:
        tx.description = data["description"]
    if "debit_amount" in data:
        val = data["debit_amount"]
        tx.debit_amount = float(val) if (val is not None and str(val).strip() != "") else None
    if "credit_amount" in data:
        val = data["credit_amount"]
        tx.credit_amount = float(val) if (val is not None and str(val).strip() != "") else None
    if "running_balance" in data:
        val = data["running_balance"]
        tx.running_balance = float(val) if (val is not None and str(val).strip() != "") else 0.0
        
    db.commit()
    
    # Trigger Python-based Statement Re-validation and Triage Loop
    # 1. Fetch all transactions in sequence for this statement
    stmt_txs = db.query(DBTransaction).filter(DBTransaction.statement_id == stmt.id).order_by(DBTransaction.id).all()
    
    # 2. Build list of transaction dictionaries for re-evaluation
    tx_dicts = []
    for t in stmt_txs:
        # Assemble string representation to respect repair formatting expectations
        tx_dicts.append({
            "transaction_date": t.transaction_date,
            "description": t.description,
            "debit_amount": str(t.debit_amount) if t.debit_amount is not None else "",
            "credit_amount": str(t.credit_amount) if t.credit_amount is not None else "",
            "running_balance": str(t.running_balance),
            "confidence": 1.0,
            "status": "clean",
            "repair_info": None,
            "additional_fields": t.additional_fields
        })
        
    # 3. Re-run math verification loop
    repaired_txs, new_repair_log, final_flags = repair_and_triage(
        opening_balance=stmt.opening_balance,
        closing_balance=stmt.closing_balance,
        transactions=tx_dicts,
        locale=stmt.detected_numeric_locale if hasattr(stmt, 'detected_numeric_locale') else "period_decimal"
    )
    
    # 4. Overwrite transaction fields in database based on new triage
    ex_rate = stmt.exchange_rate
    for idx, db_t in enumerate(stmt_txs):
        rep = repaired_txs[idx]
        db_t.status = rep["status"]
        db_t.confidence = rep["confidence"]
        db_t.debit_amount = float(rep["debit_amount"]) if (rep.get("debit_amount") and str(rep["debit_amount"]).strip() != "") else None
        db_t.credit_amount = float(rep["credit_amount"]) if (rep.get("credit_amount") and str(rep["credit_amount"]).strip() != "") else None
        db_t.running_balance = float(rep["running_balance"])
        
        # Calculate universal conversions
        db_t.universal_debit = round(db_t.debit_amount * ex_rate, 2) if db_t.debit_amount is not None else None
        db_t.universal_credit = round(db_t.credit_amount * ex_rate, 2) if db_t.credit_amount is not None else None
        db_t.universal_balance = round(db_t.running_balance * ex_rate, 2)
        
        if rep.get("repair_info"):
            db_t.repair_info = rep["repair_info"]
        else:
            db_t.repair_info_json = None
            
    # 5. Clear old and insert new audit logs
    db.query(DBAuditLog).filter(DBAuditLog.statement_id == stmt.id, DBAuditLog.log_type == "repair_attempt").delete()
    for entry in new_repair_log:
        db_log = DBAuditLog(
            statement_id=stmt.id,
            log_type="repair_attempt",
            field_location=entry.get("field", ""),
            raw_text=entry.get("raw_value", ""),
            corrected_value=entry.get("corrected_value", ""),
            reason=entry.get("reason", "")
        )
        db.add(db_log)
        
    # Check review requirement
    any_escalated = any(t.status == "escalated" for t in stmt_txs)
    has_unparsed = db.query(DBAuditLog).filter(DBAuditLog.statement_id == stmt.id, DBAuditLog.log_type == "unparsed_line").count() > 0
    stmt.review_required = any_escalated or has_unparsed
    stmt.anomaly_flags = final_flags
    stmt.confidence = sum(t.confidence for t in stmt_txs) / len(stmt_txs) if stmt_txs else 1.0
    
    db.commit()
    
    return {"success": True, "message": "Statement re-validated."}

@app.get("/api/statements/{id}/export")
async def export_statement(
    id: int,
    flat_table: bool = False,
    db: Session = Depends(get_db)
):
    stmt = db.query(DBStatement).filter(DBStatement.id == id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
        
    transactions = db.query(DBTransaction).filter(DBTransaction.statement_id == id).order_by(DBTransaction.id).all()
    audit_logs = db.query(DBAuditLog).filter(DBAuditLog.statement_id == id).all()
    
    # 1. Reconstruct CanonicalStatement model
    metadata = StatementMetadata(
        bank_name=stmt.bank_name,
        account_number=stmt.account_number,
        statement_start_date=stmt.statement_start_date,
        statement_end_date=stmt.statement_end_date,
        detected_date_locale="DMY",
        detected_numeric_locale="period_decimal",
        vendor_name=stmt.vendor_name,
        uen=stmt.uen,
        customer_id=stmt.customer_id,
        salesman_id=stmt.salesman_id,
        term_code=stmt.term_code,
        original_currency=stmt.original_currency,
        universal_currency=stmt.universal_currency,
        exchange_rate=stmt.exchange_rate
    )
    
    tx_list = []
    for t in transactions:
        rep_info = None
        if t.repair_info:
            rep_info = RepairInfo(
                raw_value=t.repair_info["raw_value"],
                corrected_value=t.repair_info["corrected_value"],
                reason=t.repair_info["reason"]
            )
        tx_list.append(Transaction(
            transaction_date=t.transaction_date,
            description=t.description,
            debit_amount=t.debit_amount,
            credit_amount=t.credit_amount,
            running_balance=t.running_balance,
            status=t.status,
            confidence=t.confidence,
            repair_info=rep_info,
            additional_fields=t.additional_fields,
            universal_debit=t.universal_debit,
            universal_credit=t.universal_credit,
            universal_balance=t.universal_balance
        ))
        
    unparsed_list = []
    repair_log_list = []
    for log in audit_logs:
        if log.log_type == "unparsed_line":
            unparsed_list.append(UnparsedLine(
                raw_text=log.raw_text,
                source_page=log.source_page or 1,
                reason=log.reason,
                review_required=True
            ))
        else:
            repair_log_list.append({
                "field": log.field_location,
                "raw_value": log.raw_text,
                "corrected_value": log.corrected_value,
                "reason": log.reason
            })
            
    canonical = CanonicalStatement(
        statement_metadata=metadata,
        opening_balance=stmt.opening_balance,
        closing_balance=stmt.closing_balance,
        transactions=tx_list,
        confidence=stmt.confidence,
        extraction_method=stmt.extraction_method,
        source_page=stmt.source_page,
        anomaly_flags=stmt.anomaly_flags,
        unparsed_lines=unparsed_list,
        repair_log=repair_log_list
    )
    
    # 2. Save temporary exported spreadsheet
    filename = f"reconciliation_export_{stmt.id}.xlsx"
    export_path = os.path.join(UPLOAD_DIR, filename)
    
    export_to_excel(
        canonical=canonical,
        output_path=export_path,
        flat_table=flat_table,
        template_path=stmt.template_file_path
    )
    
    return FileResponse(
        path=export_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# Static Dashboard Assets mapping path
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
