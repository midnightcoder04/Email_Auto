"""
PDF Data Extraction and Renaming Script
Extracts name and Gmail from PDFs, then renames the files accordingly.
"""

import os
import re
import pdfplumber
import csv
from pathlib import Path


def extract_email_from_text(text):
    """Extract Gmail address from text."""
    # Pattern for Gmail addresses
    email_pattern = r'[a-zA-Z0-9._%+-]+@gmail\.com'
    matches = re.findall(email_pattern, text, re.IGNORECASE)
    return matches[0] if matches else None


def extract_name_from_text(text, email=None):
    """
    Extract name from text. 
    Customize this based on your PDF structure.
    """
    # Common patterns - adjust based on your PDF format
    patterns = [
        r'Name[:\s]+([A-Za-z]+\s+[A-Za-z]+)',
        r'Full Name[:\s]+([A-Za-z]+\s+[A-Za-z]+)',
        r'Recipient[:\s]+([A-Za-z]+\s+[A-Za-z]+)',
        r'Dear\s+([A-Za-z]+\s+[A-Za-z]+)',
        r'To[:\s]+([A-Za-z]+\s+[A-Za-z]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # If email exists, try to extract name from email
    if email:
        username = email.split('@')[0]
        # Convert john.doe or john_doe to John Doe
        name = re.sub(r'[._]', ' ', username).title()
        return name
    
    return None


def process_pdfs(pdf_folder, output_folder=None, csv_output="email_list.csv"):
    """
    Process all PDFs in folder:
    1. Extract name and email
    2. Rename PDF to format: email_name.pdf
    3. Create CSV mapping file
    """
    pdf_folder = Path(pdf_folder)
    output_folder = Path(output_folder) if output_folder else pdf_folder / "renamed"
    output_folder.mkdir(exist_ok=True)
    
    results = []
    errors = []
    
    pdf_files = list(pdf_folder.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files to process")
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"Processing {i}/{len(pdf_files)}: {pdf_path.name}")
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Extract text from all pages
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
            
            # Extract email and name
            email = extract_email_from_text(full_text)
            name = extract_name_from_text(full_text, email)
            
            if not email:
                errors.append({
                    'file': pdf_path.name,
                    'error': 'No Gmail found'
                })
                print(f"  ⚠ No Gmail found in {pdf_path.name}")
                continue
            
            # Create new filename: email_name.pdf or just email.pdf
            safe_name = re.sub(r'[^\w\s-]', '', name or '').replace(' ', '_') if name else ''
            safe_email = email.replace('@gmail.com', '')
            
            if safe_name:
                new_filename = f"{safe_email}_{safe_name}.pdf"
            else:
                new_filename = f"{safe_email}.pdf"
            
            # Copy/rename to output folder
            new_path = output_folder / new_filename
            
            # Handle duplicate filenames
            counter = 1
            while new_path.exists():
                if safe_name:
                    new_filename = f"{safe_email}_{safe_name}_{counter}.pdf"
                else:
                    new_filename = f"{safe_email}_{counter}.pdf"
                new_path = output_folder / new_filename
                counter += 1
            
            # Copy file to new location with new name
            import shutil
            shutil.copy2(pdf_path, new_path)
            
            results.append({
                'original_file': pdf_path.name,
                'new_file': new_filename,
                'email': email,
                'name': name or '',
                'pdf_path': str(new_path)
            })
            
            print(f"  ✓ {email} - {name or 'No name'}")
            
        except Exception as e:
            errors.append({
                'file': pdf_path.name,
                'error': str(e)
            })
            print(f"  ✗ Error: {e}")
    
    # Save results to CSV
    csv_path = output_folder / csv_output
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['email', 'name', 'pdf_path', 'original_file', 'new_file'])
        writer.writeheader()
        writer.writerows(results)
    
    # Save errors to separate file
    if errors:
        error_path = output_folder / "errors.csv"
        with open(error_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['file', 'error'])
            writer.writeheader()
            writer.writerows(errors)
    
    print(f"\n{'='*50}")
    print(f"Successfully processed: {len(results)} files")
    print(f"Errors: {len(errors)} files")
    print(f"CSV saved to: {csv_path}")
    if errors:
        print(f"Errors saved to: {output_folder / 'errors.csv'}")
    
    return results, errors


if __name__ == "__main__":
    # CONFIGURE THESE PATHS
    PDF_FOLDER = "./pdfs"  # Folder containing your PDFs
    OUTPUT_FOLDER = "./renamed_pdfs"  # Where renamed PDFs will go
    
    results, errors = process_pdfs(PDF_FOLDER, OUTPUT_FOLDER)
