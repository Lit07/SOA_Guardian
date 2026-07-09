import os
import csv
import pytest
from fpdf import FPDF
from soa_guardian.pipeline import process_statement
from soa_guardian.vendor_registry import VendorRegistry

def create_unnamed_aragen_pdf(file_path: str):
    """Generates an unnamed PDF with 'Aragen' mentioned in the text layer."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    
    # Metadata headers containing the vendor name
    pdf.cell(200, 8, text="Aragen Life Sciences Pvt Ltd", ln=True)
    pdf.cell(200, 8, text="Account Number: ACC-88899", ln=True)
    pdf.cell(200, 8, text="Opening Balance: 1000.00", ln=True)
    pdf.cell(200, 8, text="Closing Balance: 3000.00", ln=True)
    pdf.ln(5)
    
    # Table headers matching Aragen column template
    pdf.cell(30, 8, text="Date", border=1)
    pdf.cell(60, 8, text="Particulars", border=1)
    pdf.cell(30, 8, text="Debit", border=1)
    pdf.cell(30, 8, text="Credit", border=1)
    pdf.cell(30, 8, text="Balance", border=1)
    pdf.ln()
    
    # Row 1
    pdf.cell(30, 8, text="01/06/2026", border=1)
    pdf.cell(60, 8, text="Opening Balance", border=1)
    pdf.cell(30, 8, text="", border=1)
    pdf.cell(30, 8, text="", border=1)
    pdf.cell(30, 8, text="1000.00", border=1)
    pdf.ln()
    
    # Row 2
    pdf.cell(30, 8, text="02/06/2026", border=1)
    pdf.cell(60, 8, text="Invoice Payment", border=1)
    pdf.cell(30, 8, text="", border=1)
    pdf.cell(30, 8, text="2000.00", border=1)
    pdf.cell(30, 8, text="3000.00", border=1)
    pdf.ln()
    
    pdf.output(file_path)

def create_unnamed_sigma_csv(file_path: str):
    """Generates an unnamed CSV with Sigma columns but no mention of Sigma in text."""
    data = [
        ["Account Number: ACC-9990", "", "", "", ""],
        ["Opening Balance: 500.00", "", "", "", ""],
        [],
        # Table headers match Sigma configuration exactly
        ["TxnDate", "Narrative", "Dr", "Cr", "CumBal"],
        ["01/06/2026", "Opening Balance", "", "", "500.00"],
        ["02/06/2026", "Chemical supplies", "150.00", "", "350.00"],
        ["03/06/2026", "Rebate credit", "", "100.00", "450.00"],
        [],
        ["Closing Balance: 450.00", "", "", "", ""]
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(data)

def test_vendor_registry_loading():
    """Verify that vendor mappings config loads successfully."""
    registry = VendorRegistry()
    assert "aragen_pvt_ltd" in registry.vendors
    assert "sigma_aldrich" in registry.vendors

def test_aragen_text_identification():
    """Verify vendor is matched by text aliases inside an unnamed PDF file."""
    pdf_path = "tests/unnamed_aragen_statement.pdf"
    create_unnamed_aragen_pdf(pdf_path)
    
    try:
        canonical = process_statement(pdf_path)
        # Assert that the system resolved bank_name to the vendor name
        assert canonical.statement_metadata.bank_name == "Aragen Life Sciences Pvt Ltd"
        assert canonical.opening_balance == 1000.00
        assert canonical.closing_balance == 3000.00
        assert len(canonical.transactions) == 2
        assert canonical.transactions[1].description == "Invoice Payment"
        assert canonical.transactions[1].credit_amount == 2000.00
        assert canonical.transactions[1].status == "clean"
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

def test_sigma_layout_identification():
    """Verify vendor is matched by column header structure in an unnamed spreadsheet."""
    csv_path = "tests/unnamed_sigma_statement.csv"
    create_unnamed_sigma_csv(csv_path)
    
    try:
        canonical = process_statement(csv_path)
        # Assert that the system fuzzy matched column headers to Sigma-Aldrich
        assert canonical.statement_metadata.bank_name == "Sigma-Aldrich Chemicals"
        assert canonical.opening_balance == 500.00
        assert canonical.closing_balance == 450.00
        assert len(canonical.transactions) == 3
        assert canonical.transactions[1].description == "Chemical supplies"
        assert canonical.transactions[1].debit_amount == 150.00
        assert canonical.transactions[2].credit_amount == 100.00
        assert canonical.transactions[2].status == "clean"
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)


def test_cocacola_mapping_prefers_document_type_over_reference_key():
    """Verify the workbook mapping resolves the description field from the document-type column instead of the reference key."""
    mapping_path = "Internship Problem Statement Docs/SOA-Mapping.xlsx"
    registry = VendorRegistry(mappings_path=mapping_path)

    coca_key = next(
        (key for key, config in registry.vendors.items() if config.get("official_name", "").lower().startswith("coca")),
        None
    )

    assert coca_key is not None
    assert registry.vendors[coca_key]["columns"]["description"] == "Document Type"


def test_real_cocacola_statement_uses_mapping_workbook():
    """Verify the real Coca-Cola workbook is parsed to transactions using the provided mapping workbook."""
    statement_path = "Internship Problem Statement Docs/SoAs/Coca-Cola Singapore Beverages Pte Ltd.xlsx"
    mapping_path = "Internship Problem Statement Docs/SOA-Mapping.xlsx"

    canonical = process_statement(
        statement_path,
        custom_mapping_path=mapping_path,
        original_filename=os.path.basename(statement_path)
    )

    assert canonical.header_mapping
    assert len(canonical.transactions) > 0
    assert canonical.output_format_columns
    assert canonical.transactions[0].transaction_date
