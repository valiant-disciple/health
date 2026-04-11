"""
Lab OCR pipeline
  Primary:  Spike API → LOINC-normalized structured JSON
  Fallback: pypdf text extraction + GPT-4o-mini JSON extraction
"""
from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from openai import AsyncOpenAI

from config import settings
from services.db import get_supabase

log = structlog.get_logger()

SPIKE_BASE = "https://api.spikeapi.com/v1"

# ─── LOINC lookup — top-40 common lab tests ──────────────────────────────────

LOINC_MAP: dict[str, str] = {
    "hemoglobin": "718-7",
    "hematocrit": "4544-3",
    "wbc": "6690-2",
    "white blood cell": "6690-2",
    "white blood count": "6690-2",
    "rbc": "789-8",
    "red blood cell": "789-8",
    "platelets": "777-3",
    "platelet count": "777-3",
    "mcv": "787-2",
    "mch": "785-6",
    "mchc": "786-4",
    "rdw": "788-0",
    "neutrophil": "770-8",
    "lymphocyte": "731-0",
    "monocyte": "742-7",
    "eosinophil": "711-2",
    "glucose": "2345-7",
    "fasting glucose": "2345-7",
    "hba1c": "4548-4",
    "hemoglobin a1c": "4548-4",
    "a1c": "4548-4",
    "sodium": "2951-2",
    "potassium": "2823-3",
    "chloride": "2075-0",
    "bicarbonate": "1963-8",
    "bun": "3094-0",
    "blood urea nitrogen": "3094-0",
    "creatinine": "2160-0",
    "egfr": "62238-1",
    "calcium": "17861-6",
    "total protein": "2885-2",
    "albumin": "1751-7",
    "total bilirubin": "1975-2",
    "alt": "1742-6",
    "alanine aminotransferase": "1742-6",
    "ast": "1920-8",
    "aspartate aminotransferase": "1920-8",
    "alkaline phosphatase": "6768-6",
    "alp": "6768-6",
    "total cholesterol": "2093-3",
    "cholesterol": "2093-3",
    "hdl": "2085-9",
    "hdl cholesterol": "2085-9",
    "ldl": "13457-7",
    "ldl cholesterol": "13457-7",
    "triglycerides": "2571-8",
    "tsh": "3016-3",
    "thyroid stimulating": "3016-3",
    "t4": "3026-2",
    "t3": "3053-6",
    "vitamin d": "1989-3",
    "25-hydroxy": "1989-3",
    "vitamin b12": "2132-9",
    "ferritin": "2276-4",
    "iron": "2498-4",
    "tibc": "2501-5",
    "transferrin saturation": "14801-1",
    "uric acid": "3084-1",
    "magnesium": "19123-9",
    "phosphorus": "2777-1",
    "psa": "2857-1",
}


def _lookup_loinc(test_name: str) -> str:
    lower = test_name.lower().strip()
    for key, code in LOINC_MAP.items():
        if key in lower:
            return code
    return ""


# ─── Main pipeline ─────────────────────────────────────────────────────────

async def process_lab_report(report_id: str, user_id: str, file_path: str) -> None:
    """Full OCR pipeline — runs in background, updates DB throughout."""
    db = await get_supabase()

    # Mark as processing
    await db.table("lab_reports").update({
        "processing_status": "processing"
    }).eq("id", report_id).execute()

    try:
        # Download PDF from Supabase Storage
        pdf_bytes: bytes = await db.storage.from_("lab-reports").download(file_path)
        log.info("ocr.downloaded", report_id=report_id, size_kb=len(pdf_bytes) // 1024)

        # Extract structured results
        if settings.SPIKE_API_KEY:
            raw = await _spike_process(pdf_bytes, report_id)
        else:
            raw = await _local_extract(pdf_bytes, report_id)

        results = raw.get("results", [])
        lab_date = raw.get("report_date") or datetime.now(timezone.utc).date().isoformat()

        # Persist
        await _store_lab_results(report_id, user_id, results, lab_date)

        await db.table("lab_reports").update({
            "processing_status": "completed",
            "lab_name":          raw.get("lab_name"),
            "report_date":       raw.get("report_date"),
            "ocr_raw":           json.dumps(raw)[:10000],  # cap storage
            "processed_at":      datetime.now(timezone.utc).isoformat(),
        }).eq("id", report_id).execute()

        log.info("ocr.done", report_id=report_id, n_results=len(results))

    except Exception as exc:
        log.error("ocr.failed", report_id=report_id, error=str(exc))
        try:
            await db.table("lab_reports").update({
                "processing_status": "failed",
                "ocr_raw": json.dumps({"error": str(exc)}),
            }).eq("id", report_id).execute()
        except Exception:
            pass  # best-effort — don't raise inside error handler


# ─── Spike API ──────────────────────────────────────────────────────────────

async def _spike_process(pdf_bytes: bytes, report_id: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{SPIKE_BASE}/parse",
            headers={"Authorization": f"Bearer {settings.SPIKE_API_KEY}"},
            files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
        )
        resp.raise_for_status()
    data = resp.json()
    log.info("ocr.spike_done", report_id=report_id, n=len(data.get("results", [])))
    return data


# ─── Local fallback: pypdf + GPT-4o-mini ────────────────────────────────────

async def _local_extract(pdf_bytes: bytes, report_id: str) -> dict:
    text = _extract_pdf_text(pdf_bytes)
    log.info("ocr.pypdf_extracted", report_id=report_id, chars=len(text))

    results = await _gpt_extract(text, report_id)
    return {"results": results, "source": "local"}


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages[:20]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


_LAB_SYSTEM = """\
You are a medical data extraction engine. Extract every individual lab test result from the provided lab report text.

Return a JSON object with this exact structure — no other text:
{
  "results": [
    {
      "test_name": "Full test name as printed",
      "value": "numeric value as a string",
      "unit": "unit of measurement or null",
      "ref_range_low": numeric lower bound or null,
      "ref_range_high": numeric upper bound or null,
      "ref_range_text": "reference range as printed e.g. '3.5-5.0' or null",
      "flag": "H if high, L if low, null if normal or not shown",
      "status": "normal | high | low | critical"
    }
  ],
  "report_date": "YYYY-MM-DD if visible else null",
  "lab_name": "laboratory name if visible else null",
  "ordering_provider": "doctor name if visible else null"
}

Rules:
- Extract EVERY individual test result — not panel headings or summaries
- Derive flag and status from the value vs reference range if not explicitly printed
- status=critical when value is >150% or <50% of reference range
- Return empty results array if no results found — never fail
"""


async def _gpt_extract(text: str, report_id: str) -> list:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    resp = await client.chat.completions.create(
        model=settings.FAST_MODEL,
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _LAB_SYSTEM},
            {"role": "user", "content": f"Extract lab results:\n\n{text[:8000]}"},
        ],
    )

    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    results = data.get("results", [])
    log.info("ocr.gpt_extracted", report_id=report_id, n=len(results))
    return results


# ─── Result persistence ──────────────────────────────────────────────────────

async def _store_lab_results(
    report_id: str,
    user_id: str,
    results: list,
    lab_date: str,
) -> None:
    if not results:
        return

    db = await get_supabase()
    lab_rows = []
    event_rows = []

    for r in results:
        # Parse numeric value
        raw_val = str(r.get("value") or "")
        try:
            value_numeric: Optional[float] = float(re.sub(r"[^\d.\-]", "", raw_val))
        except (ValueError, TypeError):
            value_numeric = None

        loinc_code = r.get("loinc_code") or _lookup_loinc(r.get("test_name", ""))
        status = _derive_status(
            value_numeric,
            r.get("ref_range_low"),
            r.get("ref_range_high"),
            r.get("flag"),
        )

        lab_rows.append({
            "report_id":      report_id,
            "user_id":        user_id,
            "loinc_code":     loinc_code or r.get("test_name", "unknown"),
            "loinc_name":     r.get("test_name", "unknown"),
            "display_name":   r.get("test_name"),
            "value_numeric":  value_numeric,
            "value_text":     raw_val if value_numeric is None else None,
            "unit":           r.get("unit"),
            "ref_range_low":  r.get("ref_range_low"),
            "ref_range_high": r.get("ref_range_high"),
            "ref_range_text": r.get("ref_range_text"),
            "status":         status,
            "flag":           r.get("flag"),
            "occurred_at":    lab_date,
        })

        event_rows.append({
            "user_id":        user_id,
            "event_type":     "lab_result",
            "occurred_at":    lab_date,
            "source":         "lab_report",
            "biomarker_code": loinc_code or r.get("test_name", "unknown"),
            "biomarker_name": r.get("test_name"),
            "value_numeric":  value_numeric,
            "value_text":     raw_val if value_numeric is None else None,
            "unit":           r.get("unit"),
            "reference_low":  r.get("ref_range_low"),
            "reference_high": r.get("ref_range_high"),
            "status":         status,
            "detail_table":   "lab_results",
        })

    await db.table("lab_results").insert(lab_rows).execute()
    await db.table("health_events").insert(event_rows).execute()

    # Store each lab result as a Graphiti episode (fire and forget)
    asyncio.create_task(_store_lab_episodes(user_id, event_rows))
    # Store a clinical memory summary in Mem0 for long-term recall
    asyncio.create_task(_store_clinical_memory_from_labs(user_id, event_rows, lab_date))


def _derive_status(
    value: Optional[float],
    ref_low: Optional[float],
    ref_high: Optional[float],
    flag: Optional[str],
) -> str:
    if flag:
        upper = flag.upper()
        if upper == "H":
            return "high"
        if upper == "L":
            return "low"
        if upper in ("HH", "LL", "CRITICAL"):
            return "critical"
    if value is None:
        return "normal"
    if ref_high is not None and value > ref_high * 1.5:
        return "critical"
    if ref_low is not None and ref_low > 0 and value < ref_low * 0.5:
        return "critical"
    if ref_high is not None and value > ref_high:
        return "high"
    if ref_low is not None and value < ref_low:
        return "low"
    return "normal"


async def _store_clinical_memory_from_labs(
    user_id: str,
    event_rows: list[dict],
    lab_date: str,
) -> None:
    """Build a human-readable lab summary and store it in Mem0 as a clinical memory."""
    from services.memory import store_clinical_memory
    if not event_rows:
        return
    lines = [f"Lab results from {lab_date}:"]
    for e in event_rows:
        if e.get("value_numeric") is not None:
            lines.append(
                f"- {e.get('biomarker_name', e.get('biomarker_code', '?'))}: "
                f"{e['value_numeric']} {e.get('unit', '')} [{e.get('status', 'unknown')}]"
            )
    if len(lines) > 1:
        await store_clinical_memory(user_id, "\n".join(lines))


async def _store_lab_episodes(user_id: str, event_rows: list[dict]) -> None:
    """Store each lab event as a Graphiti episode for bi-temporal KG ingestion."""
    from services.memory import store_health_episode
    for event in event_rows:
        try:
            await store_health_episode(user_id, event)
        except Exception as e:
            log.warning("ocr.graphiti_episode_failed", error=str(e), exc_info=True)


# ─── Query ───────────────────────────────────────────────────────────────────

async def get_lab_results_for_report(report_id: str, user_id: str) -> list:
    db = await get_supabase()
    resp = await db.table("lab_results") \
        .select("*") \
        .eq("report_id", report_id) \
        .eq("user_id", user_id) \
        .execute()
    return resp.data or []
