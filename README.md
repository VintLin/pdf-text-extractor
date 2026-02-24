# PDF Layout Extractor

A high-quality PDF text extraction library that preserves proper reading order, especially optimized for complex layout PDFs like books, magazines, and technical documents.

## Demo

Visualization of text extraction on a sample page:

![Page 3 with Text Mask](examples/page3_text_mask.png)

- **Green mask**: Content text
- **Gray mask**: UI text (page numbers, headers, footers)

## Features

- **Smart Layout Detection**: Automatically detects and handles multi-column layouts
- **Text Direction Support**: Handles horizontal, vertical, and rotated text
- **UI Text Filtering**: Intelligent filtering of headers, footers, and page numbers
- **Proper Reading Order**: Maintains correct reading order even with complex layouts
- **Font Analysis**: Analyzes fonts to distinguish content from UI elements

## Installation

```bash
pip install pdf-text-extractor
```

Or install from source:

```bash
git clone https://github.com/VintLin/pdf-text-extractor.git
cd pdf-text-extractor
pip install -e .
```

## Quick Start

```python
from pdf_layout_extractor import PDFTextExtractor

# Basic usage
extractor = PDFTextExtractor("document.pdf")
pages = extractor.extract_text_by_page()

for page_num, lines in pages.items():
    print(f"--- Page {page_num} ---")
    for line in lines:
        print(line)

# Or get all text as a single string
extractor = PDFTextExtractor("document.pdf")
text = extractor.extract_text()
print(text)
```

## Advanced Usage

### Extract with UI filtering disabled

```python
extractor = PDFTextExtractor("document.pdf")
pages = extractor.extract_text_by_page(filter_ui_text=False)
```

### Analyze fonts before extraction

```python
extractor = PDFTextExtractor("document.pdf")
font_info = extractor.analyze_fonts()

for font_key, info in font_info.items():
    print(f"Font: {font_key}")
    print(f"  Is UI: {info['is_ui']}")
    print(f"  Unique chars: {info['unique_chars']}")
```

### Get raw content information

This helps distinguish between "no text" (needs OCR) vs "text filtered out":

```python
extractor = PDFTextExtractor("document.pdf")
pages, raw_has_content = extractor.extract_text_by_page_with_raw_info()

for page_num in pages:
    if not raw_has_content[page_num]:
        print(f"Page {page_num} may need OCR")
```

### Visualize text masks

Generate an image with text masks overlayed to visualize what text is being extracted:

```python
from pdf_layout_extractor import PDFTextExtractor

extractor = PDFTextExtractor("document.pdf")

# Save page 3 with text masks
extractor.save_page_with_text_mask(
    page_number=3,
    output_path="page3_mask.png",
    filter_ui_text=True,  # Enable UI text filtering
    scale=2.0,  # Higher resolution
    show_content_mask=True,  # Show green mask for content
    show_ui_mask=True,  # Show gray mask for UI text
)

# Or get PIL Image directly
img = extractor.render_page_with_text_mask(
    page_number=3,
    filter_ui_text=True,
    scale=1.5,
)
img.save("output.png")
```

## Comparison with Other Libraries

This library excels at handling complex layouts compared to standard libraries:

| Feature | pdf-text-extractor | pdfminer | PyPDF2 |
|---------|---------------------|----------|--------|
| Multi-column | ✅ | ❌ | ❌ |
| Vertical text | ✅ | Partial | ❌ |
| Reading order | ✅ | ❌ | ❌ |
| UI filtering | ✅ | ❌ | ❌ |

## Requirements

- Python >= 3.8
- pdfplumber >= 0.10.0
- networkx >= 3.0

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
