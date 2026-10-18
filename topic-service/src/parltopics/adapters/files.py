"""Plain-text extraction from uploaded or downloaded files. Implements `TextExtractor`."""

from __future__ import annotations

import io
import re
import zipfile

from pypdf import PdfReader

from .openparldata import clean_text

MAX_PDF_PAGES = 40


class UnsupportedFileError(ValueError):
    pass


def _kind(data: bytes, filename: str | None, content_type: str | None) -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if data[:5] == b"%PDF-" or "pdf" in ctype or name.endswith(".pdf"):
        return "pdf"
    if data[:2] == b"PK" and (name.endswith(".docx") or "wordprocessingml" in ctype):
        return "docx"
    if "html" in ctype or name.endswith((".html", ".htm")):
        return "html"
    if ctype.startswith("text/") or name.endswith((".txt", ".md")) or not ctype:
        return "text"
    raise UnsupportedFileError(f"Unsupported file type {content_type or filename!r}. Use PDF, DOCX, HTML or text.")


class FileTextExtractor:
    def extract(self, data: bytes, *, filename: str | None = None, content_type: str | None = None) -> str:
        kind = _kind(data, filename, content_type)
        if kind == "pdf":
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages[:MAX_PDF_PAGES]]
            text = "\n\n".join(pages)
        elif kind == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", "ignore")
            text = clean_text(re.sub(r"</w:p>", "\n", xml))
        elif kind == "html":
            text = clean_text(data.decode("utf-8", "ignore"))
        else:
            text = data.decode("utf-8", "ignore")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        if not text:
            raise UnsupportedFileError("No text found in the file. Scanned PDFs need OCR first.")
        return text
