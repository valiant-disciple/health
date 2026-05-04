"""Background worker — polls the message_queue table and dispatches handlers.

Runs as a separate Render service:
  Service type:    Background Worker
  Start command:   python worker.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

import structlog

from config import get_settings
from db import close_pool, init_pool
from handlers import handle_media, handle_text
from jobs import claim_next, mark_done, mark_failed, reclaim_stuck

# ── Logging setup (matches main.py) ───────────────────────────────────────
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


# ── Job dispatch ──────────────────────────────────────────────────────────


async def _dispatch(job: dict) -> None:
    payload = job["payload"]
    job_type = payload.get("type")
    if job_type == "text":
        await handle_text(payload)
    elif job_type == "media":
        await handle_media(payload)
    else:
        raise ValueError(f"unknown job type: {job_type}")


# ── Main poll loop ────────────────────────────────────────────────────────


_should_stop = False


def _install_signal_handlers() -> None:
    def _sig(_signo, _frame):
        global _should_stop
        log.info("worker.signal_received")
        _should_stop = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)


async def run_worker() -> None:
    _init_sentry()
    await init_pool()
    _install_signal_handlers()

    worker_id = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
    log.info("worker.started", worker_id=worker_id)

    last_reclaim = 0.0
    consecutive_idle = 0

    while not _should_stop:
        # Periodically rescue stuck jobs (e.g. crashed worker)
        now = time.time()
        if now - last_reclaim > 60:
            try:
                n = await reclaim_stuck(stuck_seconds=300)
                if n:
                    log.info("worker.reclaimed", n=n)
            except Exception as e:
                log.warning("worker.reclaim_failed", error=str(e))
            last_reclaim = now

        # Try to claim a job
        try:
            job = await claim_next(worker_id)
        except Exception as e:
            log.error("worker.claim_failed", error=str(e))
            await asyncio.sleep(2.0)
            continue

        if not job:
            consecutive_idle += 1
            # Backoff: 0.5s for first few, then up to 5s when idle
            sleep_s = min(0.5 + 0.5 * consecutive_idle, 5.0)
            await asyncio.sleep(sleep_s)
            continue

        consecutive_idle = 0
        job_id = job["id"]
        job_type = (job.get("payload") or {}).get("type", "?")
        started = time.time()
        log.info("worker.job_started", id=str(job_id)[:8], type=job_type, attempt=job["attempts"])

        try:
            await asyncio.wait_for(_dispatch(job), timeout=180.0)
            await mark_done(job_id)
            elapsed = time.time() - started
            log.info("worker.job_done", id=str(job_id)[:8], elapsed_s=round(elapsed, 2))
        except asyncio.TimeoutError:
            log.error("worker.job_timeout", id=str(job_id)[:8])
            await mark_failed(job_id, "timeout (>180s)", retry_in_seconds=60)
        except Exception as e:
            log.exception("worker.job_failed", id=str(job_id)[:8], error=str(e))
            # Retry with backoff for first few attempts
            attempts = job["attempts"]
            if attempts < job["max_attempts"]:
                await mark_failed(job_id, str(e)[:500], retry_in_seconds=30 * attempts)
            else:
                await mark_failed(job_id, str(e)[:500])

    log.info("worker.exiting")
    await close_pool()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
