import sys
import re
import json
from pathlib import Path

from config import Settings

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is required. Install it using: pip install pymupdf")
    sys.exit(1)


def extract_and_clean_resume(pdf_path: str) -> str:
    """
    Reads a PDF resume, extracts the raw text, and normalizes layout artifacts
    (like erratic spacing and massive newline blocks) for clean LLM context.
    """
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"No resume file found at target path: {pdf_path}")

    print(f"Opening resume: {pdf_file.name}...")
    doc = fitz.open(pdf_file)
    raw_pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # "text" layout preserves general block positioning while reading top-to-bottom
        text = page.get_text("text")
        raw_pages.append(text)

    # Combine pages
    combined_text = "\n".join(raw_pages)

    # --- Clean PDF Layout Noise ---
    # 1. Standardize line endings and strip trailing whitespace per line
    lines = [line.strip() for line in combined_text.splitlines()]
    
    # 2. Join lines back to evaluate block structures
    processed_text = "\n".join(lines)
    
    # 3. Collapse multiple spaces down to a single space
    processed_text = re.sub(r'[ \t]+', ' ', processed_text)
    
    # 4. Collapse three or more consecutive newlines down to a clean double newline
    processed_text = re.sub(r'\n{3,}', '\n\n', processed_text)

    return processed_text.strip()


def export_context(text_content: str, output_txt_path: str, output_json_path: str):
    """Saves the cleaned context into both a human-readable text file and a structured profile JSON."""
    # Save as clean plain text
    Path(output_txt_path).write_text(text_content, encoding="utf-8")
    print(f"✅ Cleaned plain text saved to: {output_txt_path}")

    # Save as JSON configuration string ready for orchestrator integration
    profile_payload = {
        "candidate_profile": text_content
    }
    
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(profile_payload, f, indent=4, ensure_ascii=False)
    print(f"✅ Orchestrator-ready JSON context saved to: {output_json_path}")

