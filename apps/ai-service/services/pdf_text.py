"""PDF text extraction. Standalone — no settings/db dependency."""
from __future__ import annotations

import io


def extract_pdf_text(pdf_bytes: bytes, max_pages: int = 20) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages[:max_pages]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)
