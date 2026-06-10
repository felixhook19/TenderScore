"""Document text extraction: PDF, DOCX and plain text."""

from io import BytesIO

from docx import Document
from pypdf import PdfReader


class UnsupportedFormatError(Exception):
    """Raised for file types the ingester cannot parse; message is safe."""


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from a submission file by extension."""
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return _extract_pdf(data)
    if lowered.endswith(".docx"):
        return _extract_docx(data)
    if lowered.endswith(".txt"):
        return data.decode("utf-8", errors="replace")
    raise UnsupportedFormatError(
        "Only PDF, DOCX and plain-text submissions are supported."
    )


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    document = Document(BytesIO(data))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
