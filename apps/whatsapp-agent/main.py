"""WhatsApp biomarker bot — FastAPI webhook receiver.

This process owns the HTTP webhook surface from Twilio. Its job:
  1. Verify Twilio signature (anti-spoofing)
  2. Apply the cheapest guardrails (rate limits, idempotency)
  3. Look up / create the user
  4. Enqueue a job to the message_queue table
  5. Return 200 to Twilio in <3 seconds

The actual work (OCR, LLM, replies) happens in worker.py reading from the queue.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from config import get_settings
from crypto import encrypt_pii, hash_ip, hash_phone
from db import audit, close_pool, get_or_create_user, init_pool, is_message_processed
from jobs import enqueue
from twilio_client import close_http as close_twilio_http
from twilio_client import verify_signature

# ── Logging setup ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(message)s")
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger()


# ── Sentry (optional) ─────────────────────────────────────────────────────
def _init_sentry() -> None:
    s = get_settings()
    if s.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(
            dsn=s.sentry_dsn,
            environment=s.environment,
            traces_sample_rate=0.1 if s.is_prod else 1.0,
            send_default_pii=False,
        )
        log.info("sentry.initialised")


# ── App lifecycle ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_sentry()
    await init_pool()
    log.info("app.starting", env=get_settings().environment)
    yield
    log.info("app.shutting_down")
    await close_pool()
    await close_twilio_http()


app = FastAPI(title="WhatsApp Biomarker Bot", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "env": get_settings().environment})


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({"service": "whatsapp-biomarker-bot", "ok": True})


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    s = get_settings()
    form = await request.form()
    flat: dict[str, str] = {k: str(v) for k, v in form.multi_items()}

    # ── 1. Signature verification ──────────────────────────────────
    signature = request.headers.get("X-Twilio-Signature", "")
    # Reconstruct the public-facing URL (Twilio signs the URL it called)
    ext_url = f"{s.public_base_url.rstrip('/')}{request.url.path}"
    if request.url.query:
        ext_url = f"{ext_url}?{request.url.query}"
    if not verify_signature(ext_url, flat, signature):
        log.warning("webhook.bad_signature", url=ext_url)
        raise HTTPException(status_code=403, detail="bad signature")

    # ── 2. Required fields ─────────────────────────────────────────
    sender = flat.get("From", "")  # "whatsapp:+91..."
    twilio_sid = flat.get("MessageSid", "")
    body = (flat.get("Body") or "").strip()
    num_media = int(flat.get("NumMedia", "0") or "0")

    if not sender or not twilio_sid:
        log.warning("webhook.missing_fields", sender=bool(sender), sid=bool(twilio_sid))
        return _twiml_ok()

    # ── 3. Idempotency (don't double-process Twilio retries) ──────
    if await is_message_processed(twilio_sid):
        log.info("webhook.duplicate_sid", sid=twilio_sid[:12])
        return _twiml_ok()

    # ── 4. Get or create user ──────────────────────────────────────
    phone_hash = hash_phone(sender)
    phone_enc = encrypt_pii(sender)
    user = await get_or_create_user(phone_hash, phone_enc)
    if user.get("blocked"):
        log.info("webhook.blocked_user", user_id=str(user["id"])[:8])
        return _twiml_ok()

    # Audit
    client_ip = request.client.host if request.client else ""
    await audit(user["id"], "webhook_received", {
        "type": "media" if num_media > 0 else "text",
        "twilio_sid": twilio_sid[:16],
        "body_len": len(body),
    }, ip_hash=hash_ip(client_ip) if client_ip else None)

    # ── 5. Enqueue work ────────────────────────────────────────────
    if num_media > 0:
        # Take only the first media for now (Twilio rarely sends >1; queue more if needed)
        media_url = flat.get("MediaUrl0", "")
        media_type = flat.get("MediaContentType0", "")
        if media_url:
            await enqueue(user["id"], {
                "type": "media",
                "user_id": str(user["id"]),
                "sender": sender,
                "twilio_sid": twilio_sid,
                "body": body,
                "media_url": media_url,
                "media_type": media_type,
            })
            # Additional media in same message — enqueue separately
            for i in range(1, num_media):
                u = flat.get(f"MediaUrl{i}", "")
                ct = flat.get(f"MediaContentType{i}", "")
                if u:
                    await enqueue(user["id"], {
                        "type": "media",
                        "user_id": str(user["id"]),
                        "sender": sender,
                        "twilio_sid": f"{twilio_sid}_{i}",
                        "body": "",
                        "media_url": u,
                        "media_type": ct,
                    })
        else:
            log.warning("webhook.media_no_url", sid=twilio_sid[:16])
    else:
        await enqueue(user["id"], {
            "type": "text",
            "user_id": str(user["id"]),
            "sender": sender,
            "twilio_sid": twilio_sid,
            "body": body,
        })

    return _twiml_ok()


# ── TwiML helpers ─────────────────────────────────────────────────────────


def _twiml_ok() -> Response:
    """Empty TwiML — we'll send the actual reply asynchronously via REST."""
    xml = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
    return Response(content=xml, media_type="application/xml")


# ── Run with uvicorn ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=get_settings().environment == "development",
    )
