"""
PDF Table Extraction Demo

This script extracts tables from PDF files using PyMuPDF (fitz).

Installation:
    pip install pymupdf openai
"""

import fitz  # PyMuPDF - install with: pip install pymupdf
import traceback
from typing import List, Tuple
import os
from openai import OpenAI


def extract_table_from_pdf(pdf_path: str) -> List[Tuple[str, str, int]]:
    """
    Extract tables from PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        List of tuples containing (markdown_table, page_text, page_number)
    """
    md_tables = []
    pdf_document = fitz.open(pdf_path)
    print(f"Opened PDF document: {pdf_path}")

    for page_number in range(pdf_document.page_count):
        try:
            page = pdf_document.load_page(page_number)
            page_text = page.get_text("text")
            page_tables = page.find_tables()

            for table in page_tables:
                # Convert each table to markdown, attach page text and page number
                md_tables.append((table.to_markdown(), page_text, page_number))

        except Exception as e:
            print(f"Error processing page {page_number}: {traceback.format_exc()}")

    pdf_document.close()
    
    if md_tables:
        print(f"Found {len(md_tables)} table(s) in the PDF.")
        return md_tables
    else:
        print("No tables found in the PDF.")
        return []


def process_single_pdf_table(i: int, md_table_entry: Tuple[str, str, int], 
                            total_tables: int, file_name: str, file_summary: str = ""):
    """
    Process a single table from PDF:
      - Display table content
      - Display page context
      - Call LLM to generate table summary
      
    Args:
        i: Index of the table
        md_table_entry: Tuple containing (extracted_table, page_content, page_number)
        total_tables: Total number of tables
        file_name: Name of the source file
        file_summary: Summary of the file (optional)
    """
    try:
        (extracted_table, page_content, page_number) = md_table_entry
        refined_table = extracted_table
        
        print(f"\n{'='*60}")
        print(f"Table {i+1}/{total_tables} from file: {file_name}")
        print(f"Page: {page_number}")
        print(f"{'='*60}")
        print(f"\nRefined table:\n{refined_table}")
        print(f"\nPage context (first 200 chars):\n{page_content[:200]}...")
        
        # Call OpenAI GPT-4 to generate table summary
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        prompt = f"""表格内容：
{refined_table}

上下文：
{page_content}

文件名：{file_name}
"""
        if file_summary:
            prompt += f"文件摘要：{file_summary}\n"
        
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "你是一个智能AI助手，根据表格的上下文对表格内容进行补充，补充后的内容要更加准确，更加详细，更加完整。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        table_summary = completion.choices[0].message.content
        print(f"\nTable summary: {table_summary}")

    except Exception as e:
        print(f"Error processing table on page {md_table_entry[2]}: {traceback.format_exc()}")


def process_pdf_tables(md_tables: List[Tuple[str, str, int]], file_name: str, file_summary: str = ""):
    """
    Process all extracted tables from PDF.
    
    Args:
        md_tables: List of tuples containing (markdown_table, page_text, page_number)
        file_name: Name of the source file
        file_summary: Summary of the file (optional)
    """
    total_tables = len(md_tables)
    print(f"\nProcessing {total_tables} table(s)...")
    
    for i, md_table_entry in enumerate(md_tables):
        process_single_pdf_table(i, md_table_entry, total_tables, file_name, file_summary)


def main():
    """
    Demo function to extract and process tables from a PDF file.
    """
    # Example usage
    pdf_path = "example.pdf"  # Replace with your PDF path
    
    print("PDF Table Extraction Demo")
    print("=" * 60)
    
    # Extract tables from PDF
    md_tables = extract_table_from_pdf(pdf_path)
    
    # Process all extracted tables
    if md_tables:
        # Set your OpenAI API key as environment variable: export OPENAI_API_KEY="your-api-key"
        file_summary = ""  # Optional: provide file summary if available
        process_pdf_tables(md_tables, pdf_path, file_summary)
        print(f"\n{'='*60}")
        print(f"Successfully processed {len(md_tables)} table(s)")
        print(f"{'='*60}")
    else:
        print("\nNo tables to process.")


if __name__ == "__main__":
    main()
