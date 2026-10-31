
from pathlib import Path

from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract


# Windows OCR executable
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Poppler executable directory
POPPLER_PATH = (
    r"C:\Users\saran\Downloads\Release-26.09.0-0"
    r"\poppler-26.09.0\Library\bin"
)


def load_pdf(path: str) -> str:
    """Extract text from a PDF, using OCR for scanned pages."""
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()

        if not text:
            images = convert_from_path(
                str(pdf_path),
                first_page=page_number,
                last_page=page_number,
                poppler_path=POPPLER_PATH,
            )

            if images:
                text = pytesseract.image_to_string(images[0]).strip()

        if text:
            pages.append(text)

    return "\n".join(pages)
