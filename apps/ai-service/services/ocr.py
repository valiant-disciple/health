"""
Lab OCR pipeline:
  Primary:  Spike API → LOINC-normalized structured JSON
  Fallback: Docling PDF → Markdown → LLM extraction
"""
from __future__ import annotations
import httpx
import structlog

from config import settings
from services.db import get_supabase

log = structlog.get_logger()

SPIKE_BASE = "https://api.spikeapi.com/v1"


async def process_lab_report(report_id: str, user_id: str, file_path: str) -> dict:
    """Download PDF from Supabase Storage and send to Spike API."""
    db = await get_supabase()

    # Download file bytes from Supabase Storage
    response = db.storage.from_("lab-reports").download(file_path)
    pdf_bytes = response

    try:
        result = await _spike_process(pdf_bytes, report_id)
    except Exception as e:
        log.warning("ocr.spike_failed", error=str(e), fallback="docling")
        result = await _docling_fallback(pdf_bytes, report_id)

    # Mark report as processed
    await db.table("lab_reports").update({
        "processing_status": "completed",
        "ocr_raw": str(result),
    }).eq("id", report_id).execute()

    return result


async def _spike_process(pdf_bytes: bytes, report_id: str) -> dict:
    if not settings.SPIKE_API_KEY:
        raise ValueError("SPIKE_API_KEY not set")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{SPIKE_BASE}/parse",
            headers={"Authorization": f"Bearer {settings.SPIKE_API_KEY}"},
            files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
        )
        response.raise_for_status()
        data = response.json()

    log.info("ocr.spike_done", report_id=report_id, result_count=len(data.get("results", [])))
    return data


async def _docling_fallback(pdf_bytes: bytes, report_id: str) -> dict:
    """Docling: PDF → Markdown, then LLM extracts values."""
    import tempfile, os
    from docling.document_converter import DocumentConverter

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        markdown = result.document.export_to_markdown()
    finally:
        os.unlink(tmp_path)

    # LLM extraction of values from markdown
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model=settings.FAST_MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": (
                "Extract all lab test results from this report as JSON. "
                "For each result include: test_name, value, unit, reference_range, flag (H/L/normal). "
                "Return ONLY a JSON array.\n\n" + markdown[:6000]
            ),
        }],
    )
    import json, re
    text = message.content[0].text  # type: ignore
    match = re.search(r"\[.*\]", text, re.DOTALL)
    results = json.loads(match.group()) if match else []
    log.info("ocr.docling_done", report_id=report_id, result_count=len(results))
    return {"results": results, "source": "docling"}


async def get_lab_results_for_report(report_id: str, user_id: str) -> list:
    """Fetch normalized lab results from Postgres for a given report."""
    db = await get_supabase()
    response = await db.table("lab_results") \
        .select("*") \
        .eq("report_id", report_id) \
        .eq("user_id", user_id) \
        .execute()
    return response.data or []
