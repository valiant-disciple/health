"""OCR + biomarker extraction pipeline.

Two-stage:
  1. PDF/image → markdown text   (Mistral OCR primary, GPT-4o vision fallback)
  2. markdown → structured JSON  (GPT-4o-mini, JSON mode)

The vision fallback handles cases Mistral OCR struggles with (handwritten,
phone photos at extreme angles, low-res scans). Anything that fails BOTH gets
returned with status='failed' and a useful error.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from dataclasses import dataclass

import httpx
import structlog

from config import get_settings
from llm import json_chat, vision_chat

log = structlog.get_logger()

# ── PDF → image conversion (for vision fallback) ──────────────────────────


def pdf_to_images(pdf_bytes: bytes, max_pages: int = 5, dpi: int = 150) -> list[bytes]:
    """Render PDF pages to PNG bytes. Caps pages for safety."""
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        log.warning("ocr.pdf2image_missing")
        return []
    try:
        images = convert_from_bytes(pdf_bytes, dpi=dpi, last_page=max_pages, fmt="png")
        out: list[bytes] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            out.append(buf.getvalue())
        return out
    except Exception as e:
        log.warning("ocr.pdf2image_failed", error=str(e))
        return []


def extract_pdf_text_basic(pdf_bytes: bytes, max_pages: int = 20) -> str:
    """Fast pypdf extraction — works for searchable PDFs, skips scanned ones."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = [(p.extract_text() or "") for p in reader.pages[:max_pages]]
        return "\n".join(pages).strip()
    except Exception as e:
        log.warning("ocr.pypdf_failed", error=str(e))
        return ""


# ── Mistral OCR ───────────────────────────────────────────────────────────
# https://docs.mistral.ai/capabilities/document/

MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"


async def mistral_ocr_pdf(pdf_bytes: bytes) -> tuple[str, dict]:
    """Run Mistral OCR. Returns (markdown, raw_response)."""
    s = get_settings()
    if not s.mistral_api_key:
        return "", {"error": "no mistral key"}

    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    payload = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{b64}",
        },
        "include_image_base64": False,
    }
    headers = {
        "Authorization": f"Bearer {s.mistral_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(MISTRAL_OCR_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            log.warning("ocr.mistral_failed", error=str(e))
            return "", {"error": str(e)}

    pages = data.get("pages", [])
    md = "\n\n---\n\n".join(p.get("markdown", "") for p in pages)
    return md, data


# ── Vision fallback ───────────────────────────────────────────────────────

VISION_OCR_PROMPT = """\
You are extracting text from a medical lab report image.
Output ONLY the textual content as Markdown, preserving table structure.
- Keep test names, values, units, reference ranges, dates exactly as shown.
- Do not summarise, do not interpret, do not add commentary.
- If a value is unclear, write [unclear] in its place.
- Preserve section headings.
"""


async def vision_ocr_image(image_bytes: bytes, user_hash: str | None = None) -> str:
    """OCR a single image via GPT-4o vision. Returns markdown."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"
    try:
        result = await vision_chat(
            user_text="Extract all text from this lab report.",
            image_data_url=data_url,
            system=VISION_OCR_PROMPT,
            max_tokens=3000,
            user_hash=user_hash,
        )
        return result.text
    except Exception as e:
        log.warning("ocr.vision_failed", error=str(e))
        return ""


async def vision_ocr_pdf(pdf_bytes: bytes, user_hash: str | None = None) -> str:
    """OCR a PDF by converting to images and running vision per page."""
    images = pdf_to_images(pdf_bytes, max_pages=5)
    if not images:
        return ""
    pages = await asyncio.gather(
        *[vision_ocr_image(img, user_hash=user_hash) for img in images],
        return_exceptions=True,
    )
    md_parts = [p for p in pages if isinstance(p, str) and p]
    return "\n\n---\n\n".join(md_parts)


# ── Stage 2: markdown → structured biomarker JSON ─────────────────────────

STRUCT_SYSTEM = """\
You are a medical-data extraction engine. From the lab-report text below,
extract every individual lab test result. Be exhaustive but conservative —
if a number is unclear, set its value to null.

Return JSON with this exact shape:
{
  "report_date": "YYYY-MM-DD or null",
  "patient_age": "string or null",
  "patient_sex": "M | F | null",
  "report_type": "blood_panel | urine | imaging | pathology | genetic | other",
  "results": [
    {
      "test_name": "exactly as printed (e.g. 'Hemoglobin', 'LDL Cholesterol')",
      "value": <number or null>,
      "value_text": "for non-numeric like 'positive', 'negative', 'detected'",
      "unit": "mg/dL | g/dL | % | etc.",
      "ref_range_text": "the printed reference range as a string",
      "ref_range_low": <number or null>,
      "ref_range_high": <number or null>,
      "flag": "H | L | HH | LL | null   (if the lab printed a high/low flag)"
    }
  ],
  "notes": "any non-result text the LLM thinks is relevant (e.g. 'fasting status: not fasting')"
}

Rules:
  - One row per test. Do not combine multiple tests into one row.
  - Numeric values: strip commas, return as number (3.14, not "3.14").
  - If the report shows multiple panels (CBC + lipid + LFT), include them all.
  - If you see only a heading with no values yet, skip it.
  - If the document looks like an imaging/pathology/genetic report (not a numeric blood panel),
    set report_type accordingly and leave results = [].
  - Return ONLY JSON.
"""


@dataclass
class OCRResult:
    success: bool
    markdown: str
    structured: dict
    provider: str
    failure_reason: str | None = None


async def extract_from_pdf(pdf_bytes: bytes, user_hash: str | None = None) -> OCRResult:
    """Full pipeline: PDF → markdown → structured JSON."""
    s = get_settings()
    md = ""
    provider = "none"

    # Stage 1a: Mistral OCR (preferred — clean Markdown tables, works for both
    # digital and scanned PDFs). Only skipped when no API key is set.
    if s.mistral_api_key:
        md, _ = await mistral_ocr_pdf(pdf_bytes)
        if md:
            provider = "mistral"
            log.info("ocr.mistral_extracted", chars=len(md))

    # Stage 1b: pypdf fallback for searchable PDFs when Mistral is unavailable
    if not md or len(md) < 200:
        pypdf_text = extract_pdf_text_basic(pdf_bytes)
        if len(pypdf_text) > 200:
            md = pypdf_text
            provider = "pypdf"
            log.info("ocr.pypdf_extracted", chars=len(md))

    # Stage 1c: Vision fallback if everything else returned little
    if not md or len(md) < 100:
        md = await vision_ocr_pdf(pdf_bytes, user_hash=user_hash)
        if md:
            provider = "vision"
            log.info("ocr.vision_extracted", chars=len(md))

    if not md or len(md) < 50:
        return OCRResult(
            success=False,
            markdown="",
            structured={},
            provider=provider,
            failure_reason="no text extracted",
        )

    # Stage 2: markdown → structured JSON
    parsed, llm_result = await json_chat(
        messages=[
            {"role": "system", "content": STRUCT_SYSTEM},
            {"role": "user", "content": md[:15000]},  # values are always early; skip lengthy commentary
        ],
        model=s.extractor_model,
        max_tokens=6000,
        user_hash=user_hash,
        timeout=120.0,
    )

    if not parsed or "results" not in parsed:
        return OCRResult(
            success=False,
            markdown=md,
            structured={},
            provider=provider,
            failure_reason="extractor returned no structured results",
        )

    return OCRResult(
        success=True,
        markdown=md,
        structured=parsed,
        provider=provider,
    )


async def extract_from_image(image_bytes: bytes, user_hash: str | None = None) -> OCRResult:
    """Single-image variant (user sent a photo, not a PDF)."""
    s = get_settings()
    md = await vision_ocr_image(image_bytes, user_hash=user_hash)
    if not md:
        return OCRResult(False, "", {}, "vision", "vision OCR failed")

    parsed, _ = await json_chat(
        messages=[
            {"role": "system", "content": STRUCT_SYSTEM},
            {"role": "user", "content": md[:15000]},
        ],
        model=s.extractor_model,
        max_tokens=6000,
        user_hash=user_hash,
        timeout=120.0,
    )
    if not parsed or "results" not in parsed:
        return OCRResult(False, md, {}, "vision", "extractor returned no structured results")
    return OCRResult(True, md, parsed, "vision")
