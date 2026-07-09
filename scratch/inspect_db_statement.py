"""Check what the actual CanonicalStatement has for original_headers, header_mapping, output_format_columns."""
import sys, json
sys.path.insert(0, ".")

from soa_guardian.web.db import SessionLocal, DBStatement, DBTransaction

db = SessionLocal()
try:
    # Get the latest statement
    stmt = db.query(DBStatement).order_by(DBStatement.id.desc()).first()
    if not stmt:
        print("No statements found in database")
        sys.exit(1)
        
    print(f"Statement ID: {stmt.id}")
    print(f"Vendor: {stmt.vendor_name}")
    print(f"Opening Balance: {stmt.opening_balance}")
    print(f"Closing Balance: {stmt.closing_balance}")
    print(f"Original Headers: {stmt.original_headers}")
    print(f"Header Mapping: {stmt.header_mapping}")
    print(f"Output Format Columns: {stmt.output_format_columns}")
    
    # Check first 3 transactions
    txs = db.query(DBTransaction).filter(DBTransaction.statement_id == stmt.id).limit(5).all()
    print(f"\nFirst {len(txs)} transactions:")
    for tx in txs:
        print(f"  date={tx.transaction_date}, desc={tx.description}, debit={tx.debit_amount}, credit={tx.credit_amount}, balance={tx.running_balance}")
        print(f"    additional_fields={tx.additional_fields}")
        
    # Count total transactions
    total = db.query(DBTransaction).filter(DBTransaction.statement_id == stmt.id).count()
    print(f"\nTotal transactions: {total}")
    
    # Sum debits and credits
    all_txs = db.query(DBTransaction).filter(DBTransaction.statement_id == stmt.id).all()
    total_debit = sum(tx.debit_amount or 0 for tx in all_txs)
    total_credit = sum(tx.credit_amount or 0 for tx in all_txs)
    print(f"Total Debits: {total_debit}")
    print(f"Total Credits: {total_credit}")
    print(f"Opening + Credits - Debits = {stmt.opening_balance + total_credit - total_debit}")
    
finally:
    db.close()
