"""
PDF Text Extractor - Main Module

A high-quality PDF text extraction library that preserves proper reading order.
"""

import collections
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import pdfplumber
from pdfplumber.page import Page
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


@dataclass
class FontInfo:
    """Font statistics for UI text detection"""

    chars: set[str]
    total_chars: int
    content_chars: int
    decoration_chars: int
    english_chars_count: int
    chinese_chars_count: int
    unique_ratio: float
    content_unique_ratio: float
    is_ui: bool


class PDFTextExtractor:
    """
    PDF Text Extractor with intelligent layout preservation.

    This extractor is designed to handle complex PDF layouts, including:
    - Multi-column layouts
    - Mixed horizontal/vertical text
    - Text with different fonts and sizes
    - UI elements filtering
    - Various text orientations (horizontal, vertical, rotated)

    Example:
        >>> from pdf_text_extractor import PDFTextExtractor
        >>> extractor = PDFTextExtractor("document.pdf")
        >>> pages = extractor.extract_text_by_page()
        >>> for page_num, lines in pages.items():
        ...     print(f"Page {page_num}:")
        ...     for line in lines:
        ...         print(f"  {line}")
    """

    DECORATION_CHARS = frozenset("·-=_~•…─━│┃┄┅┆┇┈┉┊┋﹣－﹏—")

    def __init__(self, pdf_path: Path | str | Any, pdf_obj: Any | None = None):
        """
        Initialize the PDF text extractor.

        Args:
            pdf_path: Path to the PDF file
            pdf_obj: Optional pdfplumber PDF object (for internal use)
        """
        self._should_close_pdf = False

        if pdf_obj is not None:
            self._pdf = pdf_obj
        else:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF file not found: {pdf_path}")
            self._pdf = pdfplumber.open(pdf_path)
            self._should_close_pdf = True
            self._pdf_path = pdf_path

        self._font_infos: dict[str, FontInfo] = {}
        self._cache_filter_ui_text: bool = False
        self._cached_page_texts: dict[int, list[str]] = {}

    # ========== Context Manager Support ==========
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the PDF file and release resources."""
        if self._should_close_pdf and self._pdf:
            self._pdf.close()
            self._should_close_pdf = False

    # ========== Main Public API ==========
    def extract_text_by_page(
        self,
        filter_ui_text: bool = True,
    ) -> dict[int, list[str]]:
        """
        Extract text from PDF by page with proper reading order.

        Args:
            filter_ui_text: Whether to filter out UI elements (headers, footers, etc.)

        Returns:
            Dictionary mapping page numbers to lists of text lines
        """
        total_pages = len(self._pdf.pages)

        if self._cache_filter_ui_text != filter_ui_text:
            self._cached_page_texts = {}
            self._cache_filter_ui_text = filter_ui_text

        if not self._cached_page_texts:
            self._cached_page_texts = {}
            if filter_ui_text and not self._font_infos:
                self.analyze_fonts()

            for page_num in range(1, total_pages + 1):
                self._cached_page_texts[page_num] = []
                page = self._pdf.pages[page_num - 1]
                paragraphs = self._extract_page_text(page, filter_ui_text=filter_ui_text)
                for para in paragraphs:
                    for line in para:
                        if line and line.strip() and not all(char.isdigit() for char in line.replace("\n", "").replace(" ", "")):
                            line = re.sub(r" +", " ", line.strip())
                            self._cached_page_texts[page_num].append(line)

            if hasattr(self, "_pdf_path") and self._should_close_pdf:
                logger.info(f"[PDF Extractor] Text extraction complete: {self._pdf_path}")

        return self._cached_page_texts.copy()

    def extract_text(self, filter_ui_text: bool = True) -> str:
        """
        Extract all text from PDF as a single string.

        Args:
            filter_ui_text: Whether to filter out UI elements

        Returns:
            Complete text with page separators
        """
        pages = self.extract_text_by_page(filter_ui_text=filter_ui_text)
        result = []
        for page_num in sorted(pages.keys()):
            result.append(f"\n--- Page {page_num} ---\n")
            result.extend(pages[page_num])
        return "\n".join(result)

    def extract_text_by_page_with_raw_info(
        self,
        filter_ui_text: bool = True,
    ) -> tuple[dict[int, list[str]], dict[int, bool]]:
        """
        Extract text with additional raw content information.

        Helps distinguish between pages with no text (need OCR) vs filtered content.
        """
        total_pages = len(self._pdf.pages)
        pages: dict[int, list[str]] = {}
        raw_has_content: dict[int, bool] = {}

        if filter_ui_text and not self._font_infos:
            self.analyze_fonts()

        for page_num in range(1, total_pages + 1):
            pages[page_num] = []
            page = self._pdf.pages[page_num - 1]

            page_chars = page.chars or []
            raw_has_content[page_num] = len(page_chars) > 0

            paragraphs = self._extract_page_text(page, filter_ui_text=filter_ui_text)
            for para in paragraphs:
                for line in para:
                    if line and line.strip() and not all(char.isdigit() for char in line.replace("\n", "").replace(" ", "")):
                        line = re.sub(r" +", " ", line.strip())
                        pages[page_num].append(line)

        if hasattr(self, "_pdf_path") and self._should_close_pdf:
            logger.info(f"[PDF Extractor] Text extraction complete: {self._pdf_path}")

        return pages, raw_has_content

    def analyze_fonts(self, ui_threshold_ratio: float = 0.1, min_samples: int = 8) -> dict[str, dict[str, Any]]:
        """Analyze PDF fonts to identify UI text."""
        font_stats: dict[str, dict[str, Any]] = {}
        re_chinese = re.compile(r"[\u4e00-\u9fa5]")
        re_english = re.compile(r"[a-zA-ZāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙǕǗǙǛ]")

        for page in self._pdf.pages:
            for char in page.chars:
                char_text = char.get("text", "")
                if not char_text:
                    continue

                font_key = self._get_font_key(char.get("fontname"), char.get("size"))
                if font_key not in font_stats:
                    font_stats[font_key] = {
                        "all_unique_chars": set(),
                        "content_unique": set(),
                        "content_total": 0,
                        "decoration_unique": set(),
                        "decoration_total": 0,
                        "english_count": 0,
                        "chinese_count": 0,
                    }

                stats = font_stats[font_key]
                char_type = self._classify_char(char_text)

                if char_type != "whitespace":
                    stats["all_unique_chars"].add(char_text)

                if char_type == "content":
                    stats["content_unique"].add(char_text)
                    stats["content_total"] += 1
                    if re_english.match(char_text):
                        stats["english_count"] += 1
                    elif re_chinese.match(char_text):
                        stats["chinese_count"] += 1
                elif char_type == "decoration":
                    stats["decoration_unique"].add(char_text)
                    stats["decoration_total"] += 1

        self._font_infos.clear()
        result: dict[str, dict[str, Any]] = {}

        for font_key, stats in font_stats.items():
            all_unique_chars = stats["all_unique_chars"]
            content_unique_set = stats["content_unique"]
            content_total = stats["content_total"]
            decoration_total = stats["decoration_total"]
            english_count = stats["english_count"]
            chinese_count = stats["chinese_count"]

            content_unique_count = len(content_unique_set)
            total_count = content_total + decoration_total
            if total_count == 0:
                continue

            overall_unique_ratio = len(all_unique_chars) / total_count
            content_unique_ratio = content_unique_count / max(content_total, 1)
            english_ratio = english_count / max(content_total, 1)

            is_ui = (
                content_total >= min_samples
                and content_unique_count < 80
                and english_ratio < 0.8
                and content_unique_ratio < ui_threshold_ratio
                and not all(self._is_punctuation(char) for char in all_unique_chars)
            )

            self._font_infos[font_key] = FontInfo(
                chars=all_unique_chars.copy(),
                total_chars=total_count,
                content_chars=content_total,
                decoration_chars=decoration_total,
                english_chars_count=english_count,
                chinese_chars_count=chinese_count,
                unique_ratio=overall_unique_ratio,
                content_unique_ratio=content_unique_ratio,
                is_ui=is_ui,
            )

            result[font_key] = {
                "chars": all_unique_chars,
                "total_chars": total_count,
                "unique_chars": len(all_unique_chars),
                "content_chars": content_total,
                "content_unique": content_unique_count,
                "decoration_chars": decoration_total,
                "decoration_unique": len(stats["decoration_unique"]),
                "english_chars_count": english_count,
                "chinese_chars_count": chinese_count,
                "unique_ratio": overall_unique_ratio,
                "content_unique_ratio": content_unique_ratio,
                "is_ui": is_ui,
            }

        return collections.OrderedDict(
            sorted(result.items(), key=lambda item: item[1]["content_unique_ratio"])
        )

    # ========== Private Implementation ==========
    def _extract_page_text(self, page: Page, filter_ui_text: bool = True) -> list[list[str]]:
        """Extract text from a single page."""
        words = page.dedupe_chars().extract_words(
            x_tolerance_ratio=2,
            y_tolerance=10,
            return_chars=True,
            keep_blank_chars=True,
            use_text_flow=True,
            extra_attrs=["fontname"],
        ) or []
        if filter_ui_text:
            filter_words = [w for w in words if not self._is_ui_text(w)]
        sentences = self._merge_words(filter_words)
        paragraphs = self._merge_sentences(sentences)
        return paragraphs

    def _is_ui_text(self, word: dict) -> bool:
        """Determine if word is UI text."""
        chars = word.get("chars", [])
        if not chars or not self._font_infos:
            return False
        for char in chars:
            font_key = self._get_font_key(char.get("fontname"), char.get("size"))
            font_info = self._font_infos.get(font_key)
            char_text = char.get("text", "") or ""
            if font_info and font_info.is_ui and char_text and char_text in font_info.chars:
                return True
        return False

    # ========== Helper Methods ==========
    @staticmethod
    def _classify_char(char: str) -> str:
        """Classify character type: content / decoration / whitespace"""
        if not char:
            return "whitespace"
        if char.isspace():
            return "whitespace"
        if char in PDFTextExtractor.DECORATION_CHARS:
            return "decoration"
        return "content"

    @staticmethod
    def _round_to_half(value: float | None) -> float:
        """Round float to nearest 0.5"""
        if value is None:
            return 0.0
        return round(value * 2) / 2

    def _get_font_key(self, fontname: str | None, size: float | None) -> str:
        """Generate font key: fontname_size"""
        fontname_str = str(fontname) if fontname is not None else "unknown"
        size_str = str(self._round_to_half(size)) if size is not None else "0"
        return f"{fontname_str}_{size_str}"

    @staticmethod
    def _is_punctuation(text: str) -> bool:
        """Check if text contains only punctuation"""
        punctuation = r"\d" + r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~。，"''；：？！、·《》〈〉『』「」【】『』……——"""
        pattern = f"^[{punctuation}]*$"
        return bool(re.fullmatch(pattern, text))

    @staticmethod
    def _get_word_font_size(word: dict) -> float:
        """Get word font size, prefer chars.size, then height"""
        chars = word.get("chars", [])
        if chars:
            size = chars[-1].get("size", 15.0)
            return PDFTextExtractor._round_to_half(size)
        height = word.get("height")
        if height is not None:
            return PDFTextExtractor._round_to_half(height)
        return 15.0

    @staticmethod
    def _avg_char_height(words: list[dict], fallback: float = 15.0) -> float:
        """Calculate average character height"""
        heights: list[float] = []
        for word in words:
            for char in word.get("chars", []):
                heights.append(char.get("height", fallback))
        return sum(heights) / len(heights) if heights else fallback

    @staticmethod
    def _max_char_height(words: list[dict], fallback: float = 15.0) -> float:
        """Get maximum character height"""
        max_height: float = 0
        for word in words:
            for char in word.get("chars", []):
                current = char.get("height", fallback)
                if max_height < current:
                    max_height = current
        return max_height if max_height else fallback

    # ========== Geometry Methods ==========
    def _calculate_overlap_with_rotation(
        self,
        rect1: tuple[float, float, float, float],
        rect2: tuple[float, float, float, float],
        is_vertical_layout: bool = False,
        rotation_deg: float = 0.0,
    ) -> dict[str, float]:
        """Calculate overlap between rectangles with rotation"""
        base_axis = 0.0 if is_vertical_layout else 90.0
        axis_angle_rad = math.radians(base_axis + rotation_deg)
        cos_a = math.cos(axis_angle_rad)
        sin_a = math.sin(axis_angle_rad)

        x0_1, top1, x1_1, bottom1 = rect1
        x0_2, top2, x1_2, bottom2 = rect2

        corners1 = [(x0_1, top1), (x1_1, top1), (x0_1, bottom1), (x1_1, bottom1)]
        projs1 = [x * cos_a + y * sin_a for x, y in corners1]
        s1, e1 = min(projs1), max(projs1)

        corners2 = [(x0_2, top2), (x1_2, top2), (x0_2, bottom2), (x1_2, bottom2)]
        projs2 = [x * cos_a + y * sin_a for x, y in corners2]
        s2, e2 = min(projs2), max(projs2)

        h1, h2 = e1 - s1, e2 - s2
        if h1 == 0 or h2 == 0:
            return {"overlap_len": 0, "iou": 0.0, "coverage": 0.0}

        overlap_len = max(0, min(e1, e2) - max(s1, s2))
        union_len = h1 + h2 - overlap_len
        iou = overlap_len / union_len if union_len > 0 else 0
        coverage = overlap_len / min(h1, h2) if min(h1, h2) > 0 else 0

        return {"overlap_len": overlap_len, "iou": iou, "coverage": coverage}

    def _calculate_rect_distance(
        self,
        rect1: tuple[float, float, float, float],
        rect2: tuple[float, float, float, float],
        use_center: bool = True,
    ) -> float:
        """Calculate distance between rectangle centers"""
        if use_center:
            center1_x = (rect1[0] + rect1[2]) / 2
            center1_y = (rect1[1] + rect1[3]) / 2
            center2_x = (rect2[0] + rect2[2]) / 2
            center2_y = (rect2[1] + rect2[3]) / 2
            return math.sqrt((center1_x - center2_x) ** 2 + (center1_y - center2_y) ** 2)
        else:
            dx = max(0, rect2[0] - rect1[2], rect1[0] - rect2[2])
            dy = max(0, rect2[1] - rect1[3], rect1[1] - rect2[3])
            return math.sqrt(dx**2 + dy**2)

    @staticmethod
    def _word_to_rect(word: dict) -> tuple[float, float, float, float] | None:
        """Convert word to rectangle"""
        x0 = word.get("x0")
        top = word.get("top")
        x1 = word.get("x1")
        bottom = word.get("bottom")
        if x0 is None or top is None or x1 is None or bottom is None:
            return None
        return (x0, top, x1, bottom)

    def _char_to_rect(self, char: dict) -> tuple[float, float, float, float]:
        """Convert char to rectangle"""
        if (
            not isinstance(char, dict)
            or "matrix" not in char
            or "y0" not in char
            or "y1" not in char
        ):
            return (
                float(char.get("x0", 0) or 0),
                float(char.get("top", 0) or 0),
                float(char.get("x1", 0) or 0),
                float(char.get("bottom", 0) or 0),
            )
        stable_rect, _ = self._get_perfect_bbox(char)
        return (stable_rect[0], stable_rect[1], stable_rect[2], stable_rect[3])

    def _get_perfect_bbox(self, char: dict) -> tuple[list[float], list[tuple[float, float]]]:
        """Calculate perfect bounding box for rotated characters"""
        matrix = char['matrix']
        a, b, c, d, e, f = matrix
        adv = char.get('adv', 1.0)

        ph_1 = char['bottom'] + char['y0']
        ph_2 = char['top'] + char['y1']
        page_height = (ph_1 + ph_2) / 2

        origin = (e, f)
        vec_width = (a * adv, b * adv)
        vec_height = (c, d)

        p0 = origin
        p1 = (origin[0] + vec_width[0], origin[1] + vec_width[1])
        p2 = (origin[0] + vec_height[0], origin[1] + vec_height[1])
        p3 = (origin[0] + vec_width[0] + vec_height[0],
              origin[1] + vec_width[1] + vec_height[1])

        points_pdf = [p0, p1, p2, p3]

        points_page = []
        for px, py in points_pdf:
            points_page.append((px, page_height - py))

        xs = [p[0] for p in points_page]
        ys = [p[1] for p in points_page]

        final_bbox = [min(xs), min(ys), max(xs), max(ys)]

        return final_bbox, points_page

    def _get_char_rotation(self, char: dict) -> float:
        """Get character rotation from matrix"""
        from pdfplumber.ctm import CTM

        matrix = char.get("matrix")
        if not matrix or len(matrix) < 6:
            return 0.0
        try:
            ctm = CTM(*matrix)
            return ctm.skew_x
        except Exception:
            return 0.0

    def _get_avg_rotation(self, item: dict) -> float:
        """Get average rotation of word or char"""
        chars = item.get("chars", [item])
        if not chars:
            return 0.0
        rotations = [self._get_char_rotation(c) for c in chars]
        return sum(rotations) / len(rotations)

    def _detect_text_direction(self, chars: list[dict], new_char: dict | None = None) -> str:
        """Detect text direction from chars"""
        if not chars:
            return "ltr"

        rotations = [self._get_char_rotation(c) for c in chars]
        avg_rotation = sum(rotations) / len(rotations) if rotations else 0.0

        if 140 <= abs(avg_rotation) <= 220:
            return "reversed"
        elif 80 <= avg_rotation <= 100:
            return "vertical_down"
        elif -100 <= avg_rotation <= -80:
            return "vertical_up"

        if len(chars) < 2:
            if not new_char:
                return "ltr"
            base = chars[0]
            dx = abs((new_char.get("x0", 0) or 0) - (base.get("x0", 0) or 0))
            dy = abs((new_char.get("top", 0) or 0) - (base.get("top", 0) or 0))
            if dy > dx * 2:
                return "vertical_layout_down"
            return "ltr"

        x_deltas = [
            chars[i + 1].get("x0", 0) - chars[i].get("x0", 0)
            for i in range(len(chars) - 1)
        ]
        y_deltas = [
            chars[i + 1].get("top", 0) - chars[i].get("top", 0)
            for i in range(len(chars) - 1)
        ]
        avg_x_delta = sum(x_deltas) / len(x_deltas) if x_deltas else 0
        avg_y_delta = sum(y_deltas) / len(y_deltas) if y_deltas else 0

        if abs(avg_y_delta) > abs(avg_x_delta):
            if avg_y_delta > 0:
                return "vertical_layout_down"
            else:
                return "vertical_layout_up"

        if avg_x_delta < 0:
            return "rtl"
        return "ltr"

    def _get_sentence_direction(self, sentence: dict) -> str:
        """Get sentence text direction"""
        chars = sentence.get("chars", [])
        return self._detect_text_direction(chars)

    def _is_vertical_direction(self, direction: str) -> bool:
        """Check if direction is vertical"""
        return direction in ("vertical_down", "vertical_up", "vertical_layout_down", "vertical_layout_up")

    # ========== Character Insertion ==========
    def _insert_char_to_word(self, target_word: dict, source_word: dict) -> None:
        """Insert chars from source into target"""
        source_chars = source_word.get("chars", [])
        if not source_chars:
            return

        target_chars = target_word.get("chars", [])

        for new_char in source_chars:
            target_chars = self._insert_single_char(target_chars, new_char)

        target_word["chars"] = target_chars
        target_word["text"] = "".join(c.get("text", "") for c in target_chars)

        target_word["x0"] = min(target_word.get("x0", 0), source_word.get("x0", 0))
        target_word["x1"] = max(target_word.get("x1", 0), source_word.get("x1", 0))
        target_word["top"] = min(target_word.get("top", 0), source_word.get("top", 0))
        target_word["bottom"] = max(target_word.get("bottom", 0), source_word.get("bottom", 0))
        target_word["height"] = abs(target_word.get("bottom", 0) - target_word.get("top", 0))
        target_word["width"] = abs(target_word.get("x1", 0) - target_word.get("x0", 0))

    def _insert_single_char(self, chars: list[dict], new_char: dict) -> list[dict]:
        """Insert single char at correct position"""
        if not chars:
            return [new_char]

        direction = self._detect_text_direction(chars, new_char)

        new_rect = self._char_to_rect(new_char)
        new_x0 = new_char.get("x0", 0)
        new_top = new_char.get("top", 0)

        best_idx = 0
        best_distance = float("inf")

        for idx, char in enumerate(chars):
            char_rect = self._char_to_rect(char)
            distance = self._calculate_rect_distance(new_rect, char_rect)
            if distance < best_distance:
                best_distance = distance
                best_idx = idx

        best_char = chars[best_idx]
        best_x0 = best_char.get("x0", 0)
        best_top = best_char.get("top", 0)

        if len(chars) < 2 and direction == "ltr":
            insert_idx = best_idx if new_x0 < best_x0 else best_idx + 1
        elif direction in ("reversed", "rtl"):
            if new_x0 > best_x0:
                insert_idx = best_idx
            elif new_x0 < best_x0:
                insert_idx = best_idx + 1
            elif new_top < best_top:
                insert_idx = best_idx
            else:
                insert_idx = best_idx + 1
        elif direction in ("vertical_down", "vertical_layout_down"):
            if new_top < best_top:
                insert_idx = best_idx
            elif new_top > best_top:
                insert_idx = best_idx + 1
            elif new_x0 < best_x0:
                insert_idx = best_idx
            else:
                insert_idx = best_idx + 1
        elif direction in ("vertical_up", "vertical_layout_up"):
            if new_top > best_top:
                insert_idx = best_idx
            elif new_top < best_top:
                insert_idx = best_idx + 1
            elif new_x0 < best_x0:
                insert_idx = best_idx
            else:
                insert_idx = best_idx + 1
        else:
            if new_x0 < best_x0:
                insert_idx = best_idx
            elif new_x0 > best_x0:
                insert_idx = best_idx + 1
            elif new_top < best_top:
                insert_idx = best_idx
            else:
                insert_idx = best_idx + 1

        result = chars.copy()
        result.insert(insert_idx, new_char)
        return result

    # ========== Text Merging ==========
    def _merge_words(self, words: list[dict], distance_threshold_ratio: float = 3) -> list[dict]:
        """Merge adjacent single-character words"""
        if not words:
            return []

        new_words: list[dict] = []

        for word in words:
            word = word.copy()
            text = word.get("text", "")

            if len(text) != 1 and len(text.strip()) > 1:
                new_words.append(word)
                continue

            if not new_words:
                new_words.append(word)
                continue

            prev_word = new_words[-1]
            prev_chars = prev_word.get("chars", [])
            if not prev_chars:
                new_words.append(word)
                continue

            direction = self._detect_text_direction(prev_chars)
            rotation = self._get_avg_rotation(prev_word)
            rect_word = (word.get("x0", 0), word.get("top", 0), word.get("x1", 0), word.get("bottom", 0))
            rect_prev = (prev_word.get("x0", 0), prev_word.get("top", 0), prev_word.get("x1", 0), prev_word.get("bottom", 0))

            overlap_info = self._calculate_overlap_with_rotation(
                rect_word, rect_prev,
                is_vertical_layout=self._is_vertical_direction(direction),
                rotation_deg=rotation
            )

            if overlap_info["coverage"] < 0.4 and len(prev_word.get("text", "")) > 1:
                new_words.append(word)
                continue

            threshold = self._avg_char_height([prev_word]) * distance_threshold_ratio

            current_rect = self._word_to_rect(word)
            prev_rect = self._char_to_rect(prev_chars[-1])
            if current_rect is None or prev_rect is None:
                new_words.append(word)
                continue

            distance = self._calculate_rect_distance(prev_rect, current_rect)

            if distance > threshold:
                new_words.append(word)
                continue

            self._insert_char_to_word(prev_word, word)

        single_char_words = []
        multi_char_words = []
        for w in new_words:
            if len(w.get("text", "")) == 1:
                single_char_words.append(w)
            else:
                multi_char_words.append(w)

        if not single_char_words or not multi_char_words:
            return new_words

        merged_single_indices: set[int] = set()
        for single_idx, single_word in enumerate(single_char_words):
            single_rect = self._word_to_rect(single_word)
            if single_rect is None:
                continue

            best_match_multi_idx = None
            best_match_char_idx = None
            best_char_distance = float("inf")

            for multi_idx, multi_word in enumerate(multi_char_words):
                multi_chars = multi_word.get("chars", [])
                direction = self._detect_text_direction(multi_chars)
                threshold = self._avg_char_height([multi_word, single_word]) * distance_threshold_ratio
                for char_idx, mc in enumerate(multi_chars):
                    mc_top = mc.get("top", 0)
                    mc_bottom = mc.get("bottom", 0)
                    mc_rect = (mc.get("x0", 0), mc_top, mc.get("x1", 0), mc_bottom)

                    rotation = self._get_char_rotation(mc)
                    overlap_info = self._calculate_overlap_with_rotation(
                        single_rect, mc_rect,
                        is_vertical_layout=self._is_vertical_direction(direction),
                        rotation_deg=rotation
                    )

                    if overlap_info["coverage"] < 0.7 or overlap_info["iou"] < 0.5:
                        continue

                    char_distance = self._calculate_rect_distance(single_rect, mc_rect, False)

                    if char_distance <= threshold and char_distance < best_char_distance:
                        best_char_distance = char_distance
                        best_match_multi_idx = multi_idx
                        best_match_char_idx = char_idx

            if best_match_multi_idx is not None and best_match_char_idx is not None:
                multi_word = multi_char_words[best_match_multi_idx]
                self._insert_char_to_word(multi_word, single_word)
                merged_single_indices.add(single_idx)

        result_words = multi_char_words.copy()
        for i, sw in enumerate(single_char_words):
            if i not in merged_single_indices:
                result_words.append(sw)

        return result_words

    def _merge_sentences(self, sentences: list[dict]) -> list[list[str]]:
        """Merge sentences into paragraphs"""
        sentences_groups = self._group_sentences(sentences) or []

        paragraphs_with_pos: list[tuple[list[str], float, float]] = []
        for group in sentences_groups:
            paragraph = self._build_paragraph_from_group(group)
            if paragraph:
                paragraphs_with_pos.append(paragraph)

        paragraphs_with_pos.sort(key=lambda x: (self._round_to_half(x[2]), self._round_to_half(x[1])))
        return [para for para, _, _ in paragraphs_with_pos]

    def _group_sentences(
        self,
        words: list[dict],
        distance_threshold_ratio: float = 3,
    ) -> list[list[dict]]:
        """Group words using graph connectivity"""
        if not words:
            return []

        threshold = self._avg_char_height(words) * distance_threshold_ratio
        word_rects: list[tuple[int, tuple[float, float, float, float]]] = []
        idx_to_word: dict[int, dict] = {}

        for idx, word in enumerate(words):
            rect = self._word_to_rect(word)
            if rect is not None:
                word_rects.append((idx, rect))
                idx_to_word[idx] = word

        if not word_rects:
            return []

        graph = nx.Graph()
        for idx, rect in word_rects:
            graph.add_node(idx, rect=rect)

        num = len(word_rects)
        for i in range(num):
            idx1, rect1 = word_rects[i]
            for j in range(i + 1, num):
                idx2, rect2 = word_rects[j]
                dist = self._calculate_rect_distance(rect1, rect2, use_center=False)
                if dist <= threshold:
                    graph.add_edge(idx1, idx2)

        groups = list(nx.connected_components(graph))
        return [
            [idx_to_word[idx] for idx in group if idx in idx_to_word]
            for group in groups
            if group
        ]

    def _build_paragraph_from_group(self, group: list[dict]) -> tuple[list[str], float, float] | None:
        """Convert word group to paragraph"""
        if not group:
            return None

        adjacent_merged = self._group_adjacent_horizontally(group)

        vertical_groups, remaining_after_vertical = self._group_vertically(adjacent_merged, check_font=True, distance_limit_ratio=1.5)
        vertical_merged = [self._merge_sentence_groups(g, "") for g in vertical_groups]

        horizontal_groups, remaining_after_horizontal = self._group_horizontally(remaining_after_vertical, check_font=True)
        horizontal_merged = [self._merge_sentence_groups(g, " ") for g in horizontal_groups]

        all_sentences = vertical_merged + horizontal_merged + remaining_after_horizontal

        if not all_sentences:
            return None

        all_sentences.sort(key=lambda s: (self._round_to_half(s.get("top", 0)), self._round_to_half(s.get("x0", 0))))

        final_groups, final_remaining = self._group_vertically(all_sentences, check_font=False, distance_limit_ratio=2.5)

        merged_sentences: list[dict] = []
        for g in final_groups:
            merged = self._merge_sentence_groups(g, "\n")
            if merged.get("text"):
                merged_sentences.append(merged)

        for s in final_remaining:
            if s.get("text"):
                merged_sentences.append(s)

        if not merged_sentences:
            return None

        merged_sentences.sort(key=lambda s: (s.get("top", 0), s.get("x0", 0)))
        lines = [s["text"] for s in merged_sentences]

        x0 = min(s.get("x0", 0) for s in merged_sentences)
        top = min(s.get("top", 0) for s in merged_sentences)

        return (lines, x0, top)

    def _merge_sentence_groups(self, sentences: list[dict], join_str: str) -> dict:
        """Merge sentence group into one"""
        if not sentences:
            return {"text": "", "x0": 0, "x1": 0, "top": 0, "bottom": 0, "height": 0, "fontname": "", "chars": []}

        if len(sentences) == 1:
            return sentences[0].copy()

        texts = [s.get("text", "") for s in sentences]
        merged_text = join_str.join(texts)

        x0 = min(s.get("x0", float("inf")) for s in sentences)
        x1 = max(s.get("x1", float("-inf")) for s in sentences)
        top = min(s.get("top", float("inf")) for s in sentences)
        bottom = max(s.get("bottom", float("-inf")) for s in sentences)

        merged_chars = []
        for s in sentences:
            merged_chars.extend(s.get("chars", []))

        return {
            "text": merged_text,
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "height": bottom - top,
            "fontname": sentences[0].get("fontname", ""),
            "chars": merged_chars,
        }

    def _group_vertically(
        self, sentences: list[dict], check_font: bool = True, distance_limit_ratio: float = 1.5
    ) -> tuple[list[list[dict]], list[dict]]:
        """Group vertically adjacent text"""
        if not sentences:
            return [], []

        direction = self._get_sentence_direction(sentences[0]) if sentences else "ltr"
        is_vertical = self._is_vertical_direction(direction)

        if is_vertical:
            sorted_sentences = sorted(sentences, key=lambda s: self._round_to_half(s.get("x0", 0)), reverse=(direction == "reversed"))
        else:
            sorted_sentences = sorted(sentences, key=lambda s: self._round_to_half(s.get("top", 0)), reverse=(direction == "reversed"))

        used: set[int] = set()
        groups: list[list[dict]] = []

        for i, current in enumerate(sorted_sentences):
            if i in used:
                continue

            group = [current]
            used.add(i)

            while True:
                candidates = [
                    (j, s) for j, s in enumerate(sorted_sentences)
                    if j not in used and self._is_valid_vertical_neighbor(group[-1], s, check_font, distance_limit_ratio)
                ]
                if not candidates:
                    break
                if check_font:
                    best_idx, best = self._find_best_neighbor(group[-1], candidates)
                else:
                    best_idx = candidates[0][0]
                    best = candidates[0][1]
                group.append(best)
                used.add(best_idx)

            if len(group) > 1:
                groups.append(group)
            else:
                used.discard(i)

        remaining = [s for i, s in enumerate(sorted_sentences) if i not in used]
        return groups, remaining

    def _group_horizontally(
        self, sentences: list[dict], check_font: bool = True
    ) -> tuple[list[list[dict]], list[dict]]:
        """Group horizontally adjacent text"""
        if not sentences:
            return [], []

        direction = self._get_sentence_direction(sentences[0]) if sentences else "ltr"
        is_vertical = self._is_vertical_direction(direction)

        if is_vertical:
            sorted_sentences = sorted(sentences, key=lambda s: self._round_to_half(s.get("top", 0)))
        else:
            sorted_sentences = sorted(sentences, key=lambda s: self._round_to_half(s.get("x0", 0)))

        used: set[int] = set()
        groups: list[list[dict]] = []

        for i, current in enumerate(sorted_sentences):
            if i in used:
                continue

            group = [current]
            used.add(i)

            while True:
                candidates = [
                    (j, s) for j, s in enumerate(sorted_sentences)
                    if j not in used and self._is_valid_horizontal_neighbor(group[-1], s, check_font)
                ]
                if not candidates:
                    break
                best_idx, best = self._find_best_neighbor(group[-1], candidates)
                group.append(best)
                used.add(best_idx)

            if len(group) > 1:
                groups.append(group)
            else:
                used.discard(i)

        remaining = [s for i, s in enumerate(sorted_sentences) if i not in used]
        return groups, remaining

    def _group_adjacent_horizontally(
        self, sentences: list[dict], distance_threshold_ratio: float = 1.1
    ) -> list[dict]:
        """Group horizontally adjacent text by center distance"""
        if not sentences:
            return []

        sorted_sentences = sorted(sentences, key=lambda s: (self._round_to_half(s.get("top", 0)), self._round_to_half(s.get("x0", 0))))

        result: list[dict] = []
        used: set[int] = set()

        for i, current in enumerate(sorted_sentences):
            if i in used:
                continue

            current_chars = current.get("chars", [])
            if not current_chars:
                result.append(current)
                used.add(i)
                continue

            merge_group = [current]
            used.add(i)

            while True:
                last_sent = merge_group[-1]
                last_chars = last_sent.get("chars", [])
                if not last_chars:
                    break

                last_char = last_chars[-1]
                last_char_rect = self._char_to_rect(last_char)
                distance_threshold = last_char.get("height", 0) * distance_threshold_ratio

                best_idx: int | None = None
                best_distance = float("inf")

                for j, candidate in enumerate(sorted_sentences):
                    if j in used:
                        continue

                    candidate_chars = candidate.get("chars", [])
                    if not candidate_chars:
                        continue

                    first_char = candidate_chars[0]
                    first_char_rect = self._char_to_rect(first_char)

                    distance = self._calculate_rect_distance(last_char_rect, first_char_rect, use_center=True)

                    rotation = self._get_char_rotation(last_char)
                    vertical_overlap = self._calculate_overlap_with_rotation(
                        last_char_rect, first_char_rect,
                        is_vertical_layout=False, rotation_deg=rotation
                    )
                    overlap_ratio = vertical_overlap.get("iou", 0)

                    if overlap_ratio > 0.6 and distance < distance_threshold and distance < best_distance:
                        best_distance = distance
                        best_idx = j

                if best_idx is not None:
                    merge_group.append(sorted_sentences[best_idx])
                    used.add(best_idx)
                else:
                    break

            if len(merge_group) > 1:
                merged = self._merge_sentence_groups(merge_group, "")
                result.append(merged)
            else:
                result.append(current)

        return result

    def _is_valid_vertical_neighbor(
        self, current: dict, next_sent: dict, check_font: bool = True,
        distance_limit_ratio: float = 1.5
    ) -> bool:
        """Check if next_sent is valid vertical neighbor"""
        direction = self._get_sentence_direction(current)
        is_vertical = self._is_vertical_direction(direction)
        distance_limit = self._max_char_height([current, next_sent]) * distance_limit_ratio
        rotation = self._get_avg_rotation(current)
        rect_current = (current.get("x0", 0), current.get("top", 0), current.get("x1", 0), current.get("bottom", 0))
        rect_next = (next_sent.get("x0", 0), next_sent.get("top", 0), next_sent.get("x1", 0), next_sent.get("bottom", 0))

        if is_vertical:
            current_main = current.get("chars", [])[0].get("x0", 0)
            overlap_info = self._calculate_overlap_with_rotation(
                rect_current, rect_next, is_vertical_layout=False, rotation_deg=rotation
            )
        else:
            current_main = current.get("chars", [])[0].get("top", 0)
            current_main_end = current.get("chars", [])[0].get("bottom", 0)
            next_main = next_sent.get("chars", [])[0].get("top", 0)

            if direction in ("vertical_up", "vertical_layout_up", "reversed"):
                distance = current_main - next_main
            else:
                distance = next_main - current_main_end

            if abs(distance) > distance_limit:
                return False

            overlap_info = self._calculate_overlap_with_rotation(
                rect_current, rect_next, is_vertical_layout=True, rotation_deg=rotation
            )

        if overlap_info["coverage"] < 0.3:
            return False

        if check_font:
            current_fontname = current.get("fontname", "")
            next_fontname = next_sent.get("fontname", "")
            current_size = self._get_word_font_size(current)
            next_size = self._get_word_font_size(next_sent)

            if current_fontname != next_fontname or current_size != next_size:
                return False

        return True

    def _is_valid_horizontal_neighbor(
        self, current: dict, next_sent: dict, check_font: bool = True
    ) -> bool:
        """Check if next_sent is valid horizontal neighbor"""
        direction = self._get_sentence_direction(current)
        is_vertical = self._is_vertical_direction(direction)

        current_height = current.get("height", 15)
        tolerance = 0.2 * current_height

        current_main = current.get("top", 0)
        next_main = next_sent.get("top", 0)

        if abs(next_main - current_main) > tolerance:
            return False

        if check_font:
            current_fontname = current.get("fontname", "").split("+")[-1]
            next_fontname = next_sent.get("fontname", "").split("+")[-1]
            current_size = self._get_word_font_size(current)
            next_size = self._get_word_font_size(next_sent)

            if current_fontname != next_fontname or current_size != next_size:
                return False

        return True

    def _find_best_neighbor(
        self, current: dict, candidates: list[tuple[int, dict]]
    ) -> tuple[int, dict]:
        """Find best neighbor from candidates"""
        if not candidates:
            raise ValueError("candidates cannot be empty")

        current_x0 = current.get("x0", 0)
        current_x1 = current.get("x1", 0)
        current_rect = self._word_to_rect(current) or (current_x0, current.get("top", 0), current_x1, current.get("bottom", 0))

        best_idx = candidates[0][0]
        best_sent = candidates[0][1]
        best_score = float("inf")

        for idx, sent in candidates:
            sent_x0 = sent.get("x0", 0)
            sent_x1 = sent.get("x1", 0)
            sent_rect = self._word_to_rect(sent) or (sent_x0, sent.get("top", 0), sent_x1, sent.get("bottom", 0))

            left_align_diff = abs(current_x0 - sent_x0)
            right_align_diff = abs(current_x1 - sent_x1)
            align_score = min(left_align_diff, right_align_diff)

            distance = self._calculate_rect_distance(current_rect, sent_rect, False)

            score = align_score * 0.5 + distance

            if score < best_score:
                best_score = score
                best_idx = idx
                best_sent = sent

        return best_idx, best_sent

    # ========== Visualization Methods ==========
    def render_page_with_text_mask(
        self,
        page_number: int,
        filter_ui_text: bool = True,
        scale: float = 1.0,
        show_content_mask: bool = True,
        show_ui_mask: bool = True,
    ) -> Image.Image:
        """
        Render a page with text masks overlayed.

        Args:
            page_number: Page number (1-based)
            filter_ui_text: Whether to filter UI text when analyzing
            scale: Scale factor for the output image
            show_content_mask: Show mask for content text
            show_ui_mask: Show mask for UI text

        Returns:
            PIL Image with text masks overlayed
        """
        if page_number < 1 or page_number > len(self._pdf.pages):
            raise ValueError(f"Invalid page number: {page_number}")

        page = self._pdf.pages[page_number - 1]

        # Analyze fonts if needed for UI filtering
        if filter_ui_text and not self._font_infos:
            self.analyze_fonts()

        # Extract words with character info
        words = page.dedupe_chars().extract_words(
            x_tolerance_ratio=2,
            y_tolerance=10,
            return_chars=True,
            keep_blank_chars=True,
            use_text_flow=True,
            extra_attrs=["fontname"],
        ) or []

        # Create page image
        page_img = page.to_image(resolution=72 * scale)
        img = page_img.original

        # Get image dimensions
        img_width, img_height = img.size
        page_width = page.width
        page_height = page.height

        # Create a separate overlay layer for masks
        overlay = Image.new('RGBA', (img_width, img_height), (255, 255, 255, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Classify words as content or UI
        for word in words:
            chars = word.get("chars", [])
            if not chars:
                continue

            # Determine if this word is UI text
            is_ui = False
            if filter_ui_text and self._font_infos:
                for char in chars:
                    font_key = self._get_font_key(char.get("fontname"), char.get("size"))
                    font_info = self._font_infos.get(font_key)
                    char_text = char.get("text", "") or ""
                    if font_info and font_info.is_ui and char_text and char_text in font_info.chars:
                        is_ui = True
                        break

            # Skip based on filter settings
            if is_ui and not show_ui_mask:
                continue
            if not is_ui and not show_content_mask:
                continue

            # Get word bounding box
            x0 = word.get("x0", 0)
            top = word.get("top", 0)
            x1 = word.get("x1", 0)
            bottom = word.get("bottom", 0)

            # Draw mask (convert from PDF points to pixels)
            # pdfplumber's to_image already handles the conversion
            # but we need to account for the scale
            if scale != 1.0:
                x0_scaled = x0 * scale
                top_scaled = top * scale
                x1_scaled = x1 * scale
                bottom_scaled = bottom * scale
            else:
                x0_scaled = x0
                top_scaled = top
                x1_scaled = x1
                bottom_scaled = bottom

            # Scale coordinates to image size
            x0_img = int(x0 * img_width / page_width)
            top_img = int(top * img_height / page_height)
            x1_img = int(x1 * img_width / page_width)
            bottom_img = int(bottom * img_height / page_height)

            # Set color based on content/UI (matching factcheck-desktop style)
            if is_ui:
                # Gray for UI text
                fill_color = (120, 120, 120, 40)
                stroke_color = (120, 120, 120, 160)
            else:
                # Green for content text
                fill_color = (80, 220, 120, 50)
                stroke_color = (80, 220, 120, 180)

            # Draw rectangle on overlay layer
            overlay_draw.rectangle(
                [x0_img, top_img, x1_img, bottom_img],
                fill=fill_color,
                outline=stroke_color,
                width=2
            )

        # Composite overlay onto original image
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        result = Image.alpha_composite(img, overlay)

        return result

    def save_page_with_text_mask(
        self,
        page_number: int,
        output_path: Path | str,
        filter_ui_text: bool = True,
        scale: float = 1.0,
        show_content_mask: bool = True,
        show_ui_mask: bool = True,
    ) -> None:
        """
        Save a page with text masks to a file.

        Args:
            page_number: Page number (1-based)
            output_path: Output file path
            filter_ui_text: Whether to filter UI text when analyzing
            scale: Scale factor for the output image
            show_content_mask: Show mask for content text
            show_ui_mask: Show mask for UI text
        """
        img = self.render_page_with_text_mask(
            page_number=page_number,
            filter_ui_text=filter_ui_text,
            scale=scale,
            show_content_mask=show_content_mask,
            show_ui_mask=show_ui_mask,
        )
        img.save(output_path)
        logger.info(f"[PDF Extractor] Saved page {page_number} with text mask to {output_path}")
