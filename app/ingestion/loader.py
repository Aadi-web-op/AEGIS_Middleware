from pathlib import Path
from pypdf import PdfReader


def load_pdf(path: str) -> str:
    """
    Read a PDF and return its extracted text.
    """
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))

    pages = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            pages.append(text)

    return "\n".join(pages)