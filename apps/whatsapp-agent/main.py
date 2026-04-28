"""WhatsApp PDF vault over Twilio.

A user sends PDFs to a Twilio WhatsApp number; this service stores each one
under an LLM-generated title + summary, partitioned by sender. Later, when
the user asks for one in natural language ("send me the lab report from
March"), the service picks the right PDF and replies with it as WhatsApp
media.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from openai import OpenAI
from twilio.request_validator import RequestValidator

# Reuse the PDF text extractor from the sibling ai-service.
# `ai-service` has a hyphen so it isn't importable as a package; add it to sys.path.
_AI_SERVICE = (Path(__file__).resolve().parent.parent / "ai-service").as_posix()
if _AI_SERVICE not in sys.path:
    sys.path.insert(0, _AI_SERVICE)
from services.pdf_text import extract_pdf_text  # noqa: E402

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

BASE_DIR = Path(__file__).parent
STORE_DIR = BASE_DIR / "store"
FILES_DIR = STORE_DIR / "files"
INDEX_PATH = STORE_DIR / "index.json"
FILES_DIR.mkdir(parents=True, exist_ok=True)

_index_lock = threading.Lock()
validator = RequestValidator(TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


# ---------- index helpers ----------

def _load_index() -> dict[str, list[dict[str, Any]]]:
    if not INDEX_PATH.exists():
        return {}
    with INDEX_PATH.open() as f:
        return json.load(f)


def _save_index(idx: dict[str, list[dict[str, Any]]]) -> None:
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(idx, f, indent=2)
    tmp.replace(INDEX_PATH)


def _user_entries(sender: str) -> list[dict[str, Any]]:
    return _load_index().get(sender, [])


def _add_entry(sender: str, entry: dict[str, Any]) -> None:
    with _index_lock:
        idx = _load_index()
        idx.setdefault(sender, []).append(entry)
        _save_index(idx)


def _replace_user_entries(sender: str, entries: list[dict[str, Any]]) -> None:
    with _index_lock:
        idx = _load_index()
        if entries:
            idx[sender] = entries
        else:
            idx.pop(sender, None)
        _save_index(idx)


# ---------- TwiML ----------

def twiml(body: str, media_url: str | None = None) -> Response:
    body_xml = f"<Body>{xml_escape(body)}</Body>"
    media_xml = f"<Media>{xml_escape(media_url)}</Media>" if media_url else ""
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{body_xml}{media_xml}</Message></Response>'
    return Response(content=xml, media_type="application/xml")


# ---------- Twilio signature check ----------

async def _verify_signature(request: Request, form: dict[str, str]) -> None:
    signature = request.headers.get("X-Twilio-Signature", "")
    url = f"{PUBLIC_BASE_URL}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    if not validator.validate(url, form, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ---------- PDF + LLM ----------

def _llm_title_summary(text: str, fallback_name: str) -> dict[str, str]:
    if not text:
        return {"title": fallback_name, "summary": "(no extractable text)"}
    prompt = (
        "You are cataloguing a PDF for a personal WhatsApp vault. "
        "Given the PDF's first pages of text below, return JSON with two fields:\n"
        '  "title": a short human title, max 8 words, no quotes.\n'
        '  "summary": one or two sentences describing what the document is about.\n'
        "Text:\n"
        f"{text}"
    )
    resp = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
        title = (data.get("title") or fallback_name).strip()[:120]
        summary = (data.get("summary") or "").strip()[:400]
        return {"title": title, "summary": summary}
    except json.JSONDecodeError:
        return {"title": fallback_name, "summary": ""}


def _llm_pick(query: str, entries: list[dict[str, Any]]) -> str | None:
    catalog = [{"id": e["id"], "title": e["title"], "summary": e["summary"]} for e in entries]
    prompt = (
        "The user has a small WhatsApp PDF vault. Choose the single best PDF "
        "for their request. Match by title and summary. If nothing is a "
        'reasonable match, return {"id": null}.\n'
        f"Catalog: {json.dumps(catalog)}\n"
        f"User request: {query}\n"
        'Reply as JSON: {"id": "<id or null>"}.'
    )
    resp = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return None
    chosen = data.get("id")
    if not chosen:
        return None
    return chosen if any(e["id"] == chosen for e in entries) else None


# ---------- Twilio media download ----------

def _download_twilio_media(media_url: str, dest: Path) -> bytes:
    r = requests.get(
        media_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=60,
        allow_redirects=True,
    )
    r.raise_for_status()
    dest.write_bytes(r.content)
    return r.content


# ---------- HTTP routes ----------

@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/files/{token}.pdf")
def serve_file(token: str) -> FileResponse:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        raise HTTPException(status_code=404)
    path = FILES_DIR / f"{token}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=f"{token}.pdf")


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = await request.form()
    flat: dict[str, str] = {k: str(v) for k, v in form.multi_items()}

    await _verify_signature(request, flat)

    sender = flat.get("From", "")
    if not sender:
        return twiml("Missing sender.")

    num_media = int(flat.get("NumMedia", "0") or "0")
    body = (flat.get("Body") or "").strip()

    if num_media > 0:
        return _handle_media(sender, num_media, flat, body)
    return _handle_text(sender, body)


# ---------- handlers ----------

def _handle_media(sender: str, num_media: int, form: dict[str, str], body: str) -> Response:
    stored: list[dict[str, Any]] = []
    skipped = 0
    for i in range(num_media):
        ctype = form.get(f"MediaContentType{i}", "")
        url = form.get(f"MediaUrl{i}", "")
        if ctype != "application/pdf" or not url:
            skipped += 1
            continue
        token = secrets.token_urlsafe(12)
        path = FILES_DIR / f"{token}.pdf"
        try:
            pdf_bytes = _download_twilio_media(url, path)
        except Exception:
            skipped += 1
            continue
        try:
            text = extract_pdf_text(pdf_bytes, max_pages=3)[:6000]
        except Exception:
            text = ""
        meta = _llm_title_summary(text, fallback_name=f"PDF {token[:6]}")
        entry = {
            "id": token,
            "token": token,
            "title": meta["title"],
            "summary": meta["summary"],
            "stored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if body:
            entry["user_caption"] = body[:200]
        _add_entry(sender, entry)
        stored.append(entry)

    if not stored:
        return twiml("Only PDF attachments are supported. Nothing was stored.")

    lines = [f"Stored {len(stored)} PDF{'s' if len(stored) != 1 else ''}:"]
    for i, e in enumerate(stored, 1):
        lines.append(f"{i}. {e['title']} — {e['summary']}".rstrip(" —"))
    if skipped:
        lines.append(f"({skipped} non-PDF attachment{'s' if skipped != 1 else ''} skipped.)")
    lines.append("Send 'list' to see your library, or ask for one back any time.")
    return twiml("\n".join(lines))


_LIST_RE = re.compile(r"^(list|library|what do you have|show( me)?( my)? (pdfs|files|library))\s*$", re.I)
_CLEAR_RE = re.compile(r"^(clear|clear all|wipe|delete all|reset)\s*$", re.I)
_DELETE_RE = re.compile(r"^delete\s+(\d+)\s*$", re.I)
_HELP_RE = re.compile(r"^(help|\?|hi|hello|hey)\s*$", re.I)


def _handle_text(sender: str, body: str) -> Response:
    if not body:
        return twiml("Send me a PDF to store, or ask for one back.")

    if _HELP_RE.match(body):
        return twiml(
            "PDF vault commands:\n"
            "• Send any PDF to store it.\n"
            "• 'list' — show your stored PDFs.\n"
            "• Ask in plain English to get one back, e.g. 'send me the rental agreement'.\n"
            "• 'delete N' — remove the Nth item.\n"
            "• 'clear' — wipe your library."
        )

    entries = _user_entries(sender)

    if _LIST_RE.match(body):
        if not entries:
            return twiml("Your library is empty. Send a PDF to start.")
        lines = ["Your PDFs:"]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e['title']} — {e['summary']}".rstrip(" —"))
        return twiml("\n".join(lines))

    if _CLEAR_RE.match(body):
        if not entries:
            return twiml("Your library is already empty.")
        for e in entries:
            (FILES_DIR / f"{e['token']}.pdf").unlink(missing_ok=True)
        _replace_user_entries(sender, [])
        return twiml(f"Cleared {len(entries)} PDF(s).")

    m = _DELETE_RE.match(body)
    if m:
        n = int(m.group(1))
        if n < 1 or n > len(entries):
            return twiml(f"No item {n}. You have {len(entries)} PDF(s).")
        removed = entries.pop(n - 1)
        (FILES_DIR / f"{removed['token']}.pdf").unlink(missing_ok=True)
        _replace_user_entries(sender, entries)
        return twiml(f"Deleted: {removed['title']}")

    if not entries:
        return twiml("Your library is empty. Send a PDF to start.")

    chosen_id = _llm_pick(body, entries)
    if not chosen_id:
        lines = ["I couldn't match that. Your PDFs:"]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. {e['title']}")
        return twiml("\n".join(lines))

    entry = next(e for e in entries if e["id"] == chosen_id)
    media_url = f"{PUBLIC_BASE_URL}/files/{entry['token']}.pdf"
    return twiml(f"Here's \"{entry['title']}\".", media_url=media_url)
