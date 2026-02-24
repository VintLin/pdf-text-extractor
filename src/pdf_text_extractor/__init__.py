"""
PDF Layout Extractor - A powerful PDF text extraction library

A high-quality PDF text extraction library that preserves proper reading order,
especially optimized for complex layout PDFs like books, magazines, and technical documents.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__license__ = "MIT"

from pdf_text_extractor.extractor import PDFTextExtractor
from PIL import Image

__all__ = ["PDFTextExtractor", "Image", "__version__"]
