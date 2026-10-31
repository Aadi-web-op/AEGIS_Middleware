import logging
import os
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Optional OCR dependencies (pdf2image + pytesseract)
try:
    from pdf2image import convert_from_path
    import pytesseract

    if os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    elif Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    POPPLER_PATH = os.environ.get("POPPLER_PATH", None)
    HAS_OCR = True
except ImportError:
    convert_from_path = None
    pytesseract = None
    POPPLER_PATH = None
    HAS_OCR = False


def load_pdf(path: str) -> str:
    """Extract text from a PDF, falling back to OCR if available for scanned pages."""
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()

        if not text and HAS_OCR and convert_from_path and pytesseract:
            try:
                kwargs = {"first_page": page_number, "last_page": page_number}
                if POPPLER_PATH and Path(POPPLER_PATH).exists():
                    kwargs["poppler_path"] = POPPLER_PATH
                images = convert_from_path(str(pdf_path), **kwargs)

                if images:
                    text = pytesseract.image_to_string(images[0]).strip()
            except Exception as exc:
                logger.warning("OCR failed for page %d of %s: %s", page_number, path, exc)

        if text:
            pages.append(text)

    return "\n".join(pages)
