"""
Unit and integration tests for resume OCR pipeline, text-vs-OCR decision logic,
PaddleOCR fallback, and error handling.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.ml.parsing.paddle_ocr_service import (
    PaddleOCRService,
    OCRUnavailableError,
    OCRError,
    normalize_ocr_text,
)
from app.ml.parsing.text_extraction import (
    is_text_usable,
    extract_text,
    extract_text_with_metadata,
)
from app.ml.parsing.parser import parse_resume
from tests.pdf_builder import build_test_pdf

SAMPLE_OCR_RAW_TEXT = """
Jane Doe
jane.doe@gmail.com | +1 415-555-0132
linkedin.com/in/janedoe | github.com/janedoe

EDUCATION
B.Tech Computer Science, XYZ University, 2026
CGPA: 8.7/10

EXPERIENCE
Software Engineering Intern, Acme Corp
Worked on backend services using Python and FastAPI for 2 years.

PROJECTS
Placement Portal - Built with React, Node.js, and MongoDB

SKILLS
Python, JavaScript, ReactJS, MongoDB, Docker, k8s, Git
"""


# ---------------------------------------------------------------------------
# 1. OCR text normalization tests
# ---------------------------------------------------------------------------
def test_normalize_ocr_text_cleans_excessive_whitespace():
    raw = "  Jane   Doe   \r\n\r\n\r\n\r\n\tPython   Developer   \n\n\n\n\nFastAPI  "
    normalized = normalize_ocr_text(raw)
    assert "Jane Doe" in normalized
    assert "Python Developer" in normalized
    assert "FastAPI" in normalized
    assert "\n\n\n" not in normalized


def test_normalize_ocr_text_empty_string():
    assert normalize_ocr_text("") == ""
    assert normalize_ocr_text(None) == ""


# ---------------------------------------------------------------------------
# 2. Text usability / OCR trigger logic tests
# ---------------------------------------------------------------------------
def test_is_text_usable_true_for_digital_text():
    # Long valid resume text
    valid_text = "Jane Doe\nSoftware Engineer\nExperience: 2 years in Python and React development."
    assert is_text_usable(valid_text, page_count=1) is True


def test_is_text_usable_false_for_short_text():
    # Below minimum character threshold
    short_text = "Page 1"
    assert is_text_usable(short_text, page_count=1) is False


def test_is_text_usable_false_for_garbled_non_alphanumeric_noise():
    # Character count high but alphanumeric ratio low (symbol garbage / font encoding bug)
    garbled_text = "$%^&*()_+{}[]|\\:;\"'<>,.?/ ~`!@#$$%^&*()_+{}[]|\\:;\"'<>,.?/ ~`!@#"
    assert is_text_usable(garbled_text, page_count=1) is False


def test_is_text_usable_false_for_few_words():
    # Enough chars but not real words
    few_words = "a b c d 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0"
    assert is_text_usable(few_words, page_count=1) is False


# ---------------------------------------------------------------------------
# 3. Digital PDF extraction - PaddleOCR is NOT called
# ---------------------------------------------------------------------------
def test_extract_text_digital_pdf_bypasses_ocr(monkeypatch):
    digital_pdf = build_test_pdf([
        "John Doe",
        "john.doe@example.com | 555-0199",
        "EDUCATION",
        "B.Tech in Computer Science from National Institute of Technology, 2026",
        "EXPERIENCE",
        "Software Engineer at Global Tech, working with Python, Django, and PostgreSQL for 3 years",
        "SKILLS",
        "Python, React, Docker, MongoDB, Kubernetes, AWS",
    ])

    ocr_service_mock = MagicMock()
    monkeypatch.setattr(
        "app.ml.parsing.paddle_ocr_service.PaddleOCRService.get_instance",
        lambda: ocr_service_mock,
    )

    text, meta = extract_text_with_metadata(digital_pdf)

    # PyMuPDF should extract sufficient text and OCR must NOT be invoked
    assert "john.doe@example.com" in text
    assert meta["ocr_used"] is False
    assert meta["extraction_method"] == "pymupdf"
    assert ocr_service_mock.ocr_pdf_bytes.call_count == 0


# ---------------------------------------------------------------------------
# 4. Scanned / Image PDF - OCR fallback is invoked
# ---------------------------------------------------------------------------
def test_extract_text_scanned_pdf_invokes_ocr_fallback(monkeypatch):
    # Minimal PDF with no real text (simulating an image/scanned PDF)
    scanned_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

    mock_service = MagicMock()
    mock_service.ocr_pdf_bytes.return_value = (
        SAMPLE_OCR_RAW_TEXT.strip(),
        {"ocr_used": True, "pages_ocred": 1, "ocr_confidence": 0.94},
    )

    monkeypatch.setattr(
        "app.ml.parsing.paddle_ocr_service.PaddleOCRService.get_instance",
        lambda: mock_service,
    )

    text, meta = extract_text_with_metadata(scanned_pdf)

    assert meta["ocr_used"] is True
    assert meta["extraction_method"] == "paddleocr"
    assert meta["ocr_confidence"] == 0.94
    assert "Jane Doe" in text
    assert "jane.doe@gmail.com" in text
    mock_service.ocr_pdf_bytes.assert_called_once()


# ---------------------------------------------------------------------------
# 5. OCR returns text -> Existing Parser & Skill Normalization
# ---------------------------------------------------------------------------
def test_parse_resume_with_ocr_output_and_skill_normalization(monkeypatch):
    scanned_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

    mock_service = MagicMock()
    mock_service.ocr_pdf_bytes.return_value = (
        SAMPLE_OCR_RAW_TEXT.strip(),
        {"ocr_used": True, "pages_ocred": 1, "ocr_confidence": 0.92},
    )

    monkeypatch.setattr(
        "app.ml.parsing.paddle_ocr_service.PaddleOCRService.get_instance",
        lambda: mock_service,
    )

    parsed, raw_text, skills, exp_years = parse_resume(scanned_pdf)

    # Verify structured entity extraction
    assert parsed.name == "Jane Doe"
    assert parsed.email == "jane.doe@gmail.com"
    assert "555" in parsed.phone
    assert exp_years == 2.0
    assert parsed.parsing_metadata is not None
    assert parsed.parsing_metadata["ocr_used"] is True

    # Verify skill normalizer resolves aliases on OCR text (ReactJS -> React, k8s -> Kubernetes)
    assert "Python" in skills
    assert "React" in skills
    assert "Kubernetes" in skills
    assert "MongoDB" in skills
    assert "Docker" in skills


# ---------------------------------------------------------------------------
# 6. OCR initialization failure -> Graceful degradation
# ---------------------------------------------------------------------------
def test_ocr_initialization_failure_does_not_crash(monkeypatch):
    scanned_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

    mock_service = MagicMock()
    mock_service.ocr_pdf_bytes.side_effect = OCRUnavailableError("PaddlePaddle is not installed")

    monkeypatch.setattr(
        "app.ml.parsing.paddle_ocr_service.PaddleOCRService.get_instance",
        lambda: mock_service,
    )

    # Should not raise exception; falls back gracefully to empty/best-effort text
    text, meta = extract_text_with_metadata(scanned_pdf)
    assert meta["ocr_used"] is False


# ---------------------------------------------------------------------------
# 7. OCR returns empty output -> Parser does not crash
# ---------------------------------------------------------------------------
def test_ocr_empty_output_does_not_crash(monkeypatch):
    scanned_pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

    mock_service = MagicMock()
    mock_service.ocr_pdf_bytes.return_value = ("", {"ocr_used": True, "pages_ocred": 1, "ocr_confidence": 0.0})

    monkeypatch.setattr(
        "app.ml.parsing.paddle_ocr_service.PaddleOCRService.get_instance",
        lambda: mock_service,
    )

    parsed, raw_text, skills, exp_years = parse_resume(scanned_pdf)
    assert parsed is not None
    assert parsed.email is None
    assert skills == []


# ---------------------------------------------------------------------------
# 8. Multi-page PDF OCR handling
# ---------------------------------------------------------------------------
def test_paddle_ocr_service_ocr_pdf_bytes_multipage(monkeypatch):
    service = PaddleOCRService()

    # Mock PyMuPDF fitz Document with 2 pages
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 2
    mock_doc.__getitem__.side_effect = lambda idx: MagicMock()

    mock_fitz = MagicMock()
    mock_fitz.open.return_value.__enter__.return_value = mock_doc
    monkeypatch.setattr("fitz.open", mock_fitz.open)

    # Mock page rendering and image OCR
    monkeypatch.setattr(service, "render_pdf_page_to_image_bytes", lambda doc, idx, dpi: b"fake_png")
    monkeypatch.setattr(
        service,
        "ocr_image_bytes",
        lambda img_bytes: ("Page Content Here", 0.95),
    )

    combined_text, meta = service.ocr_pdf_bytes(b"%PDF-1.4", page_indices=[0, 1])

    assert meta["ocr_used"] is True
    assert meta["pages_ocred"] == 2
    assert meta["ocr_confidence"] == 0.95
    assert "Page Content Here" in combined_text
    assert "--- Page Break ---" in combined_text
