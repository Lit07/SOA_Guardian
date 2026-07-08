import os
import csv
import pandas as pd
from fpdf import FPDF

def create_clean_csv(file_path: str):
    """Generates a clean synthetic Statement of Account CSV file."""
    data = [
        ["SoA Guardian Bank", "", "", "", ""],
        ["Account Number: 987654321", "", "", "", ""],
        ["Statement Period: 01/06/2026 to 05/06/2026", "", "", "", ""],
        ["Opening Balance: 1000.00", "", "", "", ""],
        [],
        ["Date", "Description", "Withdrawals (Dr)", "Deposits (Cr)", "Balance"],
        ["01/06/2026", "Opening Balance", "", "", "1000.00"],
        ["02/06/2026", "Salary Credit", "", "2500.00", "3500.00"],
        ["03/06/2026", "Grocery Shop", "120.50", "", "3379.50"],
        ["04/06/2026", "Online Transfer", "300.00", "", "3079.50"],
        ["05/06/2026", "Interest Earned", "", "15.75", "3095.25"],
        [],
        ["Closing Balance: 3095.25", "", "", "", ""]
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(data)

def create_clean_xlsx(file_path: str):
    """Generates a clean synthetic Statement of Account XLSX spreadsheet."""
    data = [
        ["SoA Guardian Bank", "", "", "", ""],
        ["Account Number: 987654321", "", "", "", ""],
        ["Statement Period: 01/06/2026 to 05/06/2026", "", "", "", ""],
        ["Opening Balance: 1000.00", "", "", "", ""],
        [],
        ["Date", "Description", "Withdrawals (Dr)", "Deposits (Cr)", "Balance"],
        ["01/06/2026", "Opening Balance", "", "", "1000.00"],
        ["02/06/2026", "Salary Credit", "", "2500.00", "3500.00"],
        ["03/06/2026", "Grocery Shop", "120.50", "", "3379.50"],
        ["04/06/2026", "Online Transfer", "300.00", "", "3079.50"],
        ["05/06/2026", "Interest Earned", "", "15.75", "3095.25"],
        [],
        ["Closing Balance: 3095.25", "", "", "", ""]
    ]
    df = pd.DataFrame(data)
    df.to_excel(file_path, header=False, index=False)

def create_clean_pdf(file_path: str):
    """Generates a clean layout-compliant digital PDF Statement of Account."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    
    # Metadata headers
    pdf.cell(200, 8, txt="SoA Guardian Bank", ln=True)
    pdf.cell(200, 8, txt="Account Number: 987654321", ln=True)
    pdf.cell(200, 8, txt="Statement Period: 01/06/2026 to 05/06/2026", ln=True)
    pdf.cell(200, 8, txt="Opening Balance: 1000.00", ln=True)
    pdf.cell(200, 8, txt="Closing Balance: 3095.25", ln=True)
    pdf.ln(5)
    
    # Table headers
    pdf.cell(30, 8, txt="Date", border=1)
    pdf.cell(60, 8, txt="Description", border=1)
    pdf.cell(30, 8, txt="Withdrawals (Dr)", border=1)
    pdf.cell(30, 8, txt="Deposits (Cr)", border=1)
    pdf.cell(30, 8, txt="Balance", border=1)
    pdf.ln()
    
    # Row 1: Opening
    pdf.cell(30, 8, txt="01/06/2026", border=1)
    pdf.cell(60, 8, txt="Opening Balance", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="1000.00", border=1)
    pdf.ln()
    
    # Row 2: Salary Credit
    pdf.cell(30, 8, txt="02/06/2026", border=1)
    pdf.cell(60, 8, txt="Salary Credit", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="2500.00", border=1)
    pdf.cell(30, 8, txt="3500.00", border=1)
    pdf.ln()
    
    # Row 3: Grocery Purchase with continuation row below it
    pdf.cell(30, 8, txt="03/06/2026", border=1)
    pdf.cell(60, 8, txt="Grocery Shop Supermarket", border=1)
    pdf.cell(30, 8, txt="120.50", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="3379.50", border=1)
    pdf.ln()
    
    # Continuation row (lacks date/numbers, tests row-grouping)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(60, 8, txt="Store #55", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.ln()
    
    # Row 4: Online transfer
    pdf.cell(30, 8, txt="04/06/2026", border=1)
    pdf.cell(60, 8, txt="Online Transfer", border=1)
    pdf.cell(30, 8, txt="300.00", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="3079.50", border=1)
    pdf.ln()
    
    # Row 5: Interest Earned
    pdf.cell(30, 8, txt="05/06/2026", border=1)
    pdf.cell(60, 8, txt="Interest Earned", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="15.75", border=1)
    pdf.cell(30, 8, txt="3095.25", border=1)
    pdf.ln()
    
    pdf.output(file_path)

def create_corrupt_pdf(file_path: str):
    """Generates a corrupted digital PDF containing an OCR-confusable digit error '12O.50'."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    
    # Metadata headers
    pdf.cell(200, 8, txt="SoA Guardian Bank", ln=True)
    pdf.cell(200, 8, txt="Account Number: 987654321", ln=True)
    pdf.cell(200, 8, txt="Statement Period: 01/06/2026 to 05/06/2026", ln=True)
    pdf.cell(200, 8, txt="Opening Balance: 1000.00", ln=True)
    pdf.cell(200, 8, txt="Closing Balance: 3095.25", ln=True)
    pdf.ln(5)
    
    # Table headers
    pdf.cell(30, 8, txt="Date", border=1)
    pdf.cell(60, 8, txt="Description", border=1)
    pdf.cell(30, 8, txt="Withdrawals (Dr)", border=1)
    pdf.cell(30, 8, txt="Deposits (Cr)", border=1)
    pdf.cell(30, 8, txt="Balance", border=1)
    pdf.ln()
    
    # Row 1
    pdf.cell(30, 8, txt="01/06/2026", border=1)
    pdf.cell(60, 8, txt="Opening Balance", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="1000.00", border=1)
    pdf.ln()
    
    # Row 2 (Salary)
    pdf.cell(30, 8, txt="02/06/2026", border=1)
    pdf.cell(60, 8, txt="Salary Credit", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="2500.00", border=1)
    pdf.cell(30, 8, txt="3500.00", border=1)
    pdf.ln()
    
    # Row 3 (Grocery - WITH CORRUPT DEBIT VALUE "12O.50")
    pdf.cell(30, 8, txt="03/06/2026", border=1)
    pdf.cell(60, 8, txt="Grocery Shop Supermarket", border=1)
    pdf.cell(30, 8, txt="12O.50", border=1)  # alphabetical 'O' instead of digit '0'
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="3379.50", border=1)
    pdf.ln()
    
    # Continuation row
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(60, 8, txt="Store #55", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.ln()
    
    # Row 4 (Online transfer)
    pdf.cell(30, 8, txt="04/06/2026", border=1)
    pdf.cell(60, 8, txt="Online Transfer", border=1)
    pdf.cell(30, 8, txt="300.00", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="3079.50", border=1)
    pdf.ln()
    
    # Row 5 (Interest)
    pdf.cell(30, 8, txt="05/06/2026", border=1)
    pdf.cell(60, 8, txt="Interest Earned", border=1)
    pdf.cell(30, 8, txt="", border=1)
    pdf.cell(30, 8, txt="15.75", border=1)
    pdf.cell(30, 8, txt="3095.25", border=1)
    pdf.ln()
    
    pdf.output(file_path)

def generate_all_test_data():
    os.makedirs("tests", exist_ok=True)
    create_clean_csv("tests/clean_statement.csv")
    create_clean_xlsx("tests/clean_statement.xlsx")
    create_clean_pdf("tests/clean_pdf_statement.pdf")
    create_corrupt_pdf("tests/corrupt_pdf_statement.pdf")
    print("Test data generation complete!")

if __name__ == "__main__":
    generate_all_test_data()
