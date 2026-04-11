"""
In-memory sliding-window rate limiter.

Limits per (user_id, endpoint) pair. No Redis required — resets on restart,
which is acceptable for a single-process deployment. Replace with Redis-backed
implementation for multi-replica setups.

Defaults:
  chat     — 30 requests / 60 seconds
  interpret — 10 requests / 60 seconds
  ocr      — 5 requests / 60 seconds
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from fastapi import HTTPException
import structlog

log = structlog.get_logger()

# (user_id, endpoint) → deque of request timestamps
_windows: dict[tuple[str, str], deque] = defaultdict(deque)

LIMITS: dict[str, tuple[int, int]] = {
    # endpoint → (max_requests, window_seconds)
    "chat":      (300, 60),
    "interpret": (100, 60),
    "ocr":       (60,  60),
    "wearables": (100, 60),
    "default":   (600, 60),
}


def check_rate_limit(user_id: str, endpoint: str) -> None:
    """
    Raise HTTP 429 if the user has exceeded the rate limit for this endpoint.
    Call this at the top of each route handler.
    """
    max_requests, window_seconds = LIMITS.get(endpoint, LIMITS["default"])
    key = (user_id, endpoint)
    now = time.monotonic()
    window = _windows[key]

    # Drop timestamps outside the sliding window
    cutoff = now - window_seconds
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= max_requests:
        oldest = window[0]
        retry_after = int(window_seconds - (now - oldest)) + 1
        log.warning(
            "rate_limit.exceeded",
            user_id=user_id,
            endpoint=endpoint,
            count=len(window),
            retry_after=retry_after,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)


def get_window_count(user_id: str, endpoint: str) -> int:
    """Return current request count in the window — for testing/monitoring."""
    max_requests, window_seconds = LIMITS.get(endpoint, LIMITS["default"])
    key = (user_id, endpoint)
    now = time.monotonic()
    window = _windows[key]
    cutoff = now - window_seconds
    while window and window[0] < cutoff:
        window.popleft()
    return len(window)


def reset_limits():
    """Clear all windows — used in tests."""
    _windows.clear()
