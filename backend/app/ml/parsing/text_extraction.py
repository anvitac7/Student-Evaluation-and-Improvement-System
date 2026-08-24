"""
Extracts raw text from a resume PDF with intelligent multi-stage fallback:
1. PyMuPDF (fast, native digital text extraction).
2. pdfplumber fallback (handles unusual font encodings and odd layout structures).
3. Text quality evaluation: analyzes character count, printable/alphanumeric density,
   and layout validity.
4. PaddleOCR (PP-OCRv4) fallback: triggered automatically when text extraction yields
   insufficient, garbled, or image-only scanned content.

Normal digital PDFs bypass OCR completely to ensure sub-100ms latency.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _extract_with_pymupdf(file_bytes: bytes) -> Tuple[str, int]:
    """
    Extracts text and page count using PyMuPDF (fitz).
    Returns (extracted_text, page_count).
    """
    import fitz  # PyMuPDF

    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        page_count = len(doc)
        text = "\n".join(page.get_text() for page in doc)
        return text, page_count


def _extract_with_pdfplumber(file_bytes: bytes) -> str:
    """
    Fallback extractor using pdfplumber for PDFs with problematic font encodings.
    """
    import pdfplumber

    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def is_text_usable(text: str, page_count: int = 1) -> bool:
    """
    Evaluates whether the extracted text is sufficient and of usable quality,
    or if OCR is required (e.g. scanned image-only PDF, corrupt font map, or sparse text).

    Quality checks:
    1. Minimum character count (scales proportionally with page count).
    2. Alphanumeric ratio: prevents garbled font encoding noise from passing as valid text.
    3. Meaningful word presence: checks for presence of common resume-like words or letters.
    """
    settings = get_settings()
    cleaned = text.strip()

    # Total characters check (configurable trigger threshold)
    min_chars = max(settings.OCR_TRIGGER_MIN_CHARS, settings.OCR_TRIGGER_MIN_CHARS * page_count // 2)
    if len(cleaned) < min_chars:
        logger.info(
            "Extracted text length (%d chars) is below threshold (%d chars for %d pages).",
            len(cleaned),
            min_chars,
            page_count,
        )
        return False

    # Alphanumeric ratio check (guards against non-printable or symbol-only font extraction garbage)
    total_chars = len(cleaned)
    alnum_chars = sum(1 for c in cleaned if c.isalnum())
    ratio = alnum_chars / max(1, total_chars)

    if ratio < settings.OCR_MIN_ALPHANUMERIC_RATIO:
        logger.info(
            "Extracted text alphanumeric ratio (%.2f) is below threshold (%.2f). Text may be garbled.",
            ratio,
            settings.OCR_MIN_ALPHANUMERIC_RATIO,
        )
        return False

    # Must contain at least some multi-character words
    words = [w for w in re.split(r"\s+", cleaned) if len(w) >= 2]
    if len(words) < 5:
        logger.info("Extracted text contains fewer than 5 words (%d words found).", len(words))
        return False

    return True


def extract_text_with_metadata(file_bytes: bytes) -> Tuple[str, dict]:
    """
    Extracts text from a resume PDF and returns both the text and extraction metadata.
    Metadata includes:
      - extraction_method: 'pymupdf' | 'pdfplumber' | 'paddleocr' | 'fallback_empty'
      - ocr_used: bool
      - page_count: int
      - ocr_confidence: float (if OCR was used)
    """
    settings = get_settings()
    page_count = 1
    text = ""
    method = "pymupdf"

    # Step 1: Attempt PyMuPDF extraction
    try:
        text, page_count = _extract_with_pymupdf(file_bytes)
    except Exception:
        logger.warning("PyMuPDF failed to extract text, falling back to pdfplumber.", exc_info=True)
        text = ""

    # Step 2: Attempt pdfplumber fallback if PyMuPDF returned suspiciously little text
    if not is_text_usable(text, page_count):
        try:
            fallback_text = _extract_with_pdfplumber(file_bytes)
            if is_text_usable(fallback_text, page_count) or len(fallback_text.strip()) > len(text.strip()):
                text = fallback_text
                method = "pdfplumber"
        except Exception:
            logger.warning("pdfplumber fallback also failed.", exc_info=True)

    # Step 3: If text is still not usable and OCR is enabled, invoke PaddleOCR
    if not is_text_usable(text, page_count):
        if settings.OCR_ENABLED:
            logger.info("Digital text extraction insufficient (%d chars). Invoking PaddleOCR fallback...", len(text.strip()))
            try:
                from app.ml.parsing.paddle_ocr_service import PaddleOCRService, OCRUnavailableError

                ocr_service = PaddleOCRService.get_instance()
                ocr_text, ocr_meta = ocr_service.ocr_pdf_bytes(file_bytes)

                if ocr_text.strip():
                    logger.info(
                        "PaddleOCR succeeded: extracted %d chars across %d pages (avg conf: %.2f).",
                        len(ocr_text),
                        ocr_meta.get("pages_ocred", 0),
                        ocr_meta.get("ocr_confidence", 0.0),
                    )
                    return ocr_text, {
                        "extraction_method": "paddleocr",
                        "ocr_used": True,
                        "page_count": page_count,
                        "ocr_confidence": ocr_meta.get("ocr_confidence", 0.0),
                    }
                else:
                    logger.warning("PaddleOCR returned empty text. Retaining raw extracted text.")
            except OCRUnavailableError as exc:
                logger.warning("PaddleOCR unavailable (%s). Continuing with extracted text.", exc)
            except Exception as exc:
                logger.exception("PaddleOCR processing encountered an error: %s", exc)
        else:
            logger.info("OCR is disabled in configuration. Proceeding with best-effort extracted text.")

    # Return standard extracted text if OCR was not needed or did not produce results
    return text, {
        "extraction_method": method if text.strip() else "fallback_empty",
        "ocr_used": False,
        "page_count": page_count,
        "ocr_confidence": 0.0,
    }


def extract_text(file_bytes: bytes) -> str:
    """
    Backwards-compatible interface returning plain text string.
    """
    text, _ = extract_text_with_metadata(file_bytes)
    return text
