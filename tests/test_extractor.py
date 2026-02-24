"""
Tests for PDF Layout Extractor
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestGeometry:
    """Test geometry utilities."""

    def test_round_to_half(self):
        from pdf_text_extractor.geometry import round_to_half

        assert round_to_half(1.0) == 1.0
        assert round_to_half(1.25) == 1.5
        assert round_to_half(1.3) == 1.5
        assert round_to_half(1.7) == 1.5
        assert round_to_half(1.75) == 2.0
        assert round_to_half(None) == 0.0

    def test_calculate_overlap_with_rotation(self):
        from pdf_text_extractor.geometry import calculate_overlap_with_rotation

        # Two overlapping rectangles
        rect1 = (0, 0, 10, 10)
        rect2 = (5, 5, 15, 15)

        result = calculate_overlap_with_rotation(rect1, rect2)
        assert result["overlap_len"] > 0
        assert result["iou"] > 0
        assert result["coverage"] > 0

        # Non-overlapping rectangles
        rect3 = (0, 0, 5, 5)
        rect4 = (10, 10, 20, 20)

        result = calculate_overlap_with_rotation(rect3, rect4)
        assert result["overlap_len"] == 0
        assert result["iou"] == 0
        assert result["coverage"] == 0

    def test_calculate_rect_distance(self):
        from pdf_text_extractor.geometry import calculate_rect_distance

        # Adjacent rectangles
        rect1 = (0, 0, 10, 10)
        rect2 = (10, 0, 20, 10)

        distance = calculate_rect_distance(rect1, rect2, use_center=True)
        assert distance == 10.0

        distance = calculate_rect_distance(rect1, rect2, use_center=False)
        assert distance == 0.0  # Edge to edge


class TestExtractorInit:
    """Test extractor initialization."""

    def test_init_with_valid_path(self, tmp_path):
        """Test initialization with valid PDF path."""
        from pdf_text_extractor.extractor import PDFTextExtractor

        # Create a mock PDF for testing
        pdf_path = tmp_path / "test.pdf"
        pdf_path.touch()

        # This will fail because pdfplumber can't open the file
        # but we can test the error handling
        with pytest.raises(Exception):
            extractor = PDFTextExtractor(str(pdf_path))

    def test_init_with_nonexistent_path(self):
        """Test initialization with nonexistent path."""
        from pdf_text_extractor.extractor import PDFTextExtractor

        with pytest.raises(FileNotFoundError):
            PDFTextExtractor("/nonexistent/file.pdf")

    def test_context_manager(self):
        """Test context manager support."""
        from pdf_text_extractor.extractor import PDFTextExtractor

        # Just verify the method exists
        assert hasattr(PDFTextExtractor, '__enter__')
        assert hasattr(PDFTextExtractor, '__exit__')
        assert hasattr(PDFTextExtractor, 'close')


class TestTextGrouping:
    """Test text grouping functionality."""

    def test_detect_text_direction(self):
        """Test text direction detection."""
        from pdf_text_extractor.text_grouping import TextGrouping

        # Create a mock extractor
        mock_extractor = MagicMock()
        mock_extractor._get_char_rotation = lambda c: 0.0
        mock_extractor._char_to_rect = lambda c: (0, 0, 10, 10)

        grouping = TextGrouping(mock_extractor)

        # Empty chars should return default
        assert grouping.detect_text_direction([]) == "ltr"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
