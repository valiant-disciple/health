"""
Langfuse tracing — thin wrapper so the rest of the codebase
stays decoupled from the observability provider.

Usage:
    from services.tracing import get_tracer, trace_llm_call

All calls are no-ops when LANGFUSE_PUBLIC_KEY is not set,
so local dev / unit tests never fail due to missing credentials.
"""
from __future__ import annotations

import functools
import structlog
from config import settings

log = structlog.get_logger()

_langfuse = None


def _get_langfuse():
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        log.info("tracing.langfuse_initialised", host=settings.LANGFUSE_HOST)
    except Exception as e:
        log.warning("tracing.langfuse_init_failed", error=str(e), exc_info=True)
        _langfuse = None
    return _langfuse


def create_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
):
    """Create a Langfuse trace. Returns None if Langfuse is not configured."""
    lf = _get_langfuse()
    if lf is None:
        return None
    try:
        return lf.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )
    except Exception as e:
        log.warning("tracing.create_trace_failed", error=str(e), exc_info=True)
        return None


def trace_generation(
    trace,
    name: str,
    model: str,
    input_: str | list,
    output: str,
    usage: dict | None = None,
    metadata: dict | None = None,
):
    """Log an LLM generation span to an existing trace."""
    if trace is None:
        return
    try:
        trace.generation(
            name=name,
            model=model,
            input=input_,
            output=output,
            usage=usage or {},
            metadata=metadata or {},
        )
    except Exception as e:
        log.warning("tracing.generation_failed", error=str(e), exc_info=True)


def flush():
    """Flush pending events — call at shutdown or after eval runs."""
    lf = _get_langfuse()
    if lf is not None:
        try:
            lf.flush()
        except Exception:
            pass


def get_langfuse_callback():
    """
    Return a LangfuseCallbackHandler for LangChain/LangGraph.
    Returns None when Langfuse is not configured.
    """
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
    except Exception as e:
        log.warning("tracing.callback_init_failed", error=str(e), exc_info=True)
        return None


def reset():
    """Reset singleton — used in tests."""
    global _langfuse
    _langfuse = None
