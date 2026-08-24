"""
Dedicated OCR abstraction wrapping PaddleOCR (PP-OCRv4).

Design:
- Lazily initialized singleton: PaddleOCR models are loaded on first OCR request,
  not at application startup.
- CPU and GPU support: Configurable via OCR_USE_GPU / OCR_USE_ANGLE_CLS / OCR_LANG.
- Isolated failure: If PaddleOCR / PaddlePaddle is not installed, or model loading fails,
  or OCR fails on a page, OCRUnavailableError is raised or logged and the pipeline
  degrades gracefully without crashing FastAPI.
- PDF Page Rendering: Uses PyMuPDF (fitz) pixmaps to convert PDF pages to in-memory images
  (RGB NumPy arrays or PIL Images) at a configurable DPI, releasing memory immediately.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, List, Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OCRError(Exception):
    """Base exception for OCR errors."""
    pass


class OCRUnavailableError(OCRError):
    """Raised when PaddleOCR / PaddlePaddle is not installed or models cannot be loaded."""
    pass


def normalize_ocr_text(raw_text: str) -> str:
    """
    Normalizes raw OCR text before sending into the resume parsing pipeline:
    - Normalizes line breaks and whitespace.
    - Removes excessive repeated blank lines (3+ collapsed to 2).
    - Preserves useful bullet points and line structure.
    - Strips isolated non-printable noise characters without destroying resume data.
    """
    if not raw_text:
        return ""

    # Replace carriage returns and form feeds
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")

    # Replace tabs with single space
    text = text.replace("\t", " ")

    # Normalize horizontal whitespace on each line (collapse 2+ spaces, but preserve indentation intent lightly)
    lines = []
    for line in text.splitlines():
        cleaned_line = re.sub(r"[ ]{2,}", " ", line).strip()
        lines.append(cleaned_line)

    # Reassemble and collapse 3+ consecutive newlines to 2
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)

    return normalized.strip()


class PaddleOCRService:
    """
    Singleton service managing the PaddleOCR instance and page rendering.
    """
    _instance: Optional[PaddleOCRService] = None

    def __init__(self) -> None:
        self._ocr_engine: Any = None
        self._initialized: bool = False
        self._init_error: Optional[str] = None

    @classmethod
    def get_instance(cls) -> PaddleOCRService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Utility for testing / reloading."""
        cls._instance = None

    def _ensure_engine(self) -> Any:
        """
        Lazy loader for PaddleOCR engine.
        Reuses a single instance across requests.
        """
        if self._initialized:
            if self._ocr_engine is not None:
                return self._ocr_engine
            raise OCRUnavailableError(f"PaddleOCR is unavailable: {self._init_error}")

        settings = get_settings()

        if not settings.OCR_ENABLED:
            self._initialized = True
            self._init_error = "OCR is disabled in settings (OCR_ENABLED=False)"
            logger.info("PaddleOCR is disabled via configuration.")
            raise OCRUnavailableError(self._init_error)

        try:
            # Import PaddleOCR lazily so the app doesn't fail to boot if paddleocr is absent
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            # Check if an external python path with paddleocr is configured
            import os
            import subprocess
            custom_py = settings.OCR_PYTHON_PATH
            if custom_py and os.path.exists(custom_py):
                try:
                    # Test if the separate environment can run paddleocr
                    res = subprocess.run(
                        [custom_py, "-c", "import paddleocr; print('ok')"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if res.returncode == 0 and "ok" in res.stdout:
                        self._initialized = True
                        self._ocr_engine = "subprocess"
                        self._init_error = None
                        logger.info("PaddleOCR will be executed via external interpreter: %s", custom_py)
                        return self._ocr_engine
                except Exception as sub_exc:
                    logger.warning("Failed probing OCR external python environment: %s", sub_exc)

            self._initialized = True
            self._init_error = f"PaddleOCR / PaddlePaddle is not installed in current environment or {settings.OCR_PYTHON_PATH}: {exc}"
            logger.warning(
                "PaddleOCR import failed. OCR fallback will be unavailable. Error: %s",
                exc,
            )
            raise OCRUnavailableError(self._init_error) from exc

        try:
            logger.info(
                "Initializing PaddleOCR (lang=%s, use_gpu=%s, angle_cls=%s, version=PP-OCRv4)...",
                settings.OCR_LANG,
                settings.OCR_USE_GPU,
                settings.OCR_USE_ANGLE_CLS,
            )
            self._ocr_engine = PaddleOCR(
                use_angle_cls=settings.OCR_USE_ANGLE_CLS,
                lang=settings.OCR_LANG,
                use_gpu=settings.OCR_USE_GPU,
                ocr_version="PP-OCRv4",
                show_log=False,
            )
            self._initialized = True
            self._init_error = None
            logger.info("PaddleOCR engine successfully initialized.")
            return self._ocr_engine
        except Exception as exc:
            self._initialized = True
            self._ocr_engine = None
            self._init_error = f"Failed to initialize PaddleOCR engine: {exc}"
            logger.exception("Failed to initialize PaddleOCR engine.")
            raise OCRUnavailableError(self._init_error) from exc

    def render_pdf_page_to_image_bytes(
        self,
        doc_or_page: Any,
        page_index: int = 0,
        dpi: Optional[int] = None,
    ) -> bytes:
        """
        Renders a single PDF page into PNG image bytes using PyMuPDF (fitz).
        DPI controls the raster resolution (default from settings, e.g. 150-200 DPI).
        """
        settings = get_settings()
        target_dpi = dpi or settings.OCR_RENDER_DPI

        # Calculate scale matrix: default PDF point is 72 dpi
        zoom = target_dpi / 72.0
        import fitz  # PyMuPDF

        mat = fitz.Matrix(zoom, zoom)
        page = doc_or_page[page_index] if hasattr(doc_or_page, "__getitem__") else doc_or_page
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        # Explicitly release pixmap memory
        pix = None
        return img_bytes

    def ocr_image_bytes(self, image_bytes: bytes) -> Tuple[str, float]:
        """
        Runs PaddleOCR on raw image bytes.
        Returns:
            (page_text, average_confidence)
        """
        engine = self._ensure_engine()
        settings = get_settings()
        min_confidence = settings.OCR_CONFIDENCE_THRESHOLD

        if engine == "subprocess":
            import json
            import subprocess
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(image_bytes)
                temp_img_path = tf.name

            runner_code = f"""
import json
from paddleocr import PaddleOCR
ocr = PaddleOCR(use_angle_cls={settings.OCR_USE_ANGLE_CLS}, lang='{settings.OCR_LANG}', use_gpu={settings.OCR_USE_GPU}, show_log=False)
result = ocr.ocr(r'{temp_img_path}', cls={settings.OCR_USE_ANGLE_CLS})
lines = []
confs = []
if result and result[0]:
    for line in result[0]:
        if line and len(line) >= 2:
            tc = line[1]
            if isinstance(tc, (list, tuple)) and len(tc) >= 2:
                txt, conf = tc[0], float(tc[1])
                if conf >= {min_confidence} and txt.strip():
                    lines.append(txt.strip())
                    confs.append(conf)
print(json.dumps({{"lines": lines, "avg_conf": sum(confs)/len(confs) if confs else 0.0}}))
"""
            try:
                proc = subprocess.run(
                    [settings.OCR_PYTHON_PATH, "-c", runner_code],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    out = json.loads(proc.stdout.strip().splitlines()[-1])
                    return "\n".join(out.get("lines", [])), float(out.get("avg_conf", 0.0))
                else:
                    logger.warning("External PaddleOCR runner failed: %s", proc.stderr)
                    return "", 0.0
            finally:
                if os.path.exists(temp_img_path):
                    try:
                        os.remove(temp_img_path)
                    except Exception:
                        pass

        try:
            # In-process PaddleOCR engine
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_np = np.array(img)

            result = engine.ocr(img_np, cls=settings.OCR_USE_ANGLE_CLS)

            # Release PIL Image
            img.close()

            if not result or not result[0]:
                return "", 0.0

            lines: List[str] = []
            confidences: List[float] = []

            # Result format: list of [ [ [box_coords], (text, confidence) ], ... ]
            for line_info in result[0]:
                if not line_info or len(line_info) < 2:
                    continue
                text_conf = line_info[1]
                if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                    text_str, conf = text_conf[0], float(text_conf[1])
                elif isinstance(text_conf, str):
                    text_str, conf = text_conf, 1.0
                else:
                    continue

                if conf >= min_confidence and text_str.strip():
                    lines.append(text_str.strip())
                    confidences.append(conf)

            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            return "\n".join(lines), avg_conf

        except OCRUnavailableError:
            raise
        except Exception as exc:
            logger.warning("PaddleOCR recognition failed on image: %s", exc, exc_info=True)
            raise OCRError(f"OCR recognition failed: {exc}") from exc

    def ocr_pdf_bytes(
        self,
        file_bytes: bytes,
        page_indices: Optional[List[int]] = None,
    ) -> Tuple[str, dict]:
        """
        Renders specified (or all) PDF pages and extracts text via PaddleOCR.
        Returns:
            (combined_text, metadata_dict)
        """
        import fitz  # PyMuPDF

        settings = get_settings()
        page_texts: List[str] = []
        page_confidences: List[float] = []
        pages_processed = 0

        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            total_pages = len(doc)
            target_pages = page_indices if page_indices is not None else list(range(total_pages))

            logger.info("Running PaddleOCR on %d pages (total PDF pages: %d)...", len(target_pages), total_pages)

            for page_idx in target_pages:
                if page_idx < 0 or page_idx >= total_pages:
                    continue
                try:
                    img_bytes = self.render_pdf_page_to_image_bytes(doc, page_idx, dpi=settings.OCR_RENDER_DPI)
                    p_text, p_conf = self.ocr_image_bytes(img_bytes)
                    pages_processed += 1
                    if p_text:
                        page_texts.append(p_text)
                        if p_conf > 0:
                            page_confidences.append(p_conf)
                except Exception as exc:
                    logger.warning("OCR failed on PDF page %d: %s", page_idx + 1, exc)
                    # Continue with other pages rather than failing the entire document

        combined_text = "\n\n--- Page Break ---\n\n".join(page_texts) if len(page_texts) > 1 else ("".join(page_texts))
        normalized = normalize_ocr_text(combined_text)
        overall_conf = sum(page_confidences) / len(page_confidences) if page_confidences else 0.0

        metadata = {
            "ocr_used": True,
            "pages_ocred": pages_processed,
            "ocr_confidence": round(overall_conf, 3),
        }

        return normalized, metadata
