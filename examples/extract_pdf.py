"""
Example: Basic PDF text extraction

This example demonstrates basic usage of the PDF Layout Extractor.
"""

import sys
from pathlib import Path

# Add src to path for examples
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pdf_text_extractor import PDFTextExtractor


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf.py <pdf_file>")
        print("Example: python extract_pdf.py sample.pdf")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    print(f"Extracting text from: {pdf_path}")
    print("=" * 50)

    # Using context manager
    with PDFTextExtractor(pdf_path) as extractor:
        # Extract text by page
        pages = extractor.extract_text_by_page(filter_ui_text=True)

        for page_num, lines in sorted(pages.items()):
            print(f"\n--- Page {page_num} ---")
            for line in lines:
                print(line)

    print("\n" + "=" * 50)
    print("Extraction complete!")


if __name__ == "__main__":
    main()
