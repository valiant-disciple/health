"""OpenAI LLM client with retries, cost tracking, and provider abstraction.

All LLM calls in the app go through this module. That gives us:
  - One place to enforce timeouts / retries / abuse-tracking user IDs.
  - One place to track token usage and dollar cost per call.
  - One place to swap providers later (Anthropic, Mistral) without app changes.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Iterable

import structlog
from openai import AsyncOpenAI
from openai._exceptions import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import get_settings

log = structlog.get_logger()

# Pricing in USD per 1M tokens — keep this updated occasionally.
# Source: https://openai.com/api/pricing
_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    # model: (input_per_1m, output_per_1m)
    "gpt-4o":            (2.50, 10.00),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-mini":       (0.15,  0.60),
    "o1-mini":           (3.00, 12.00),
    "o1":               (15.00, 60.00),
    "gpt-4.1":           (2.00,  8.00),
    "gpt-4.1-mini":      (0.40,  1.60),
    "gpt-4.1-nano":      (0.10,  0.40),
    "gpt-5.4-nano":      (0.20,  1.25),
    "gpt-5-nano":        (0.10,  0.40),
}

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=get_settings().openai_api_key,
            timeout=60.0,
            max_retries=0,  # we handle retries ourselves
        )
    return _client


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    raw: Any = None  # full response object if caller needs tool calls etc.


def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    base = model.split(":")[0]  # strip any deployment suffix
    inp, outp = _PRICING_USD_PER_1M.get(base, (0.0, 0.0))
    return (tokens_in / 1_000_000) * inp + (tokens_out / 1_000_000) * outp


async def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1500,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | dict | None = None,
    user_hash: str | None = None,
    timeout: float = 60.0,
) -> LLMResult:
    """Call OpenAI chat completion with retries + cost tracking."""
    settings = get_settings()
    model = model or settings.orchestrator_model

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if user_hash:
        kwargs["user"] = user_hash  # passed to OpenAI for abuse tracking

    client = _get_client()
    last_error: Exception | None = None

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((APIConnectionError, RateLimitError)),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    ):
        with attempt:
            try:
                resp = await asyncio.wait_for(
                    client.chat.completions.create(**kwargs),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as e:
                last_error = e
                raise APIConnectionError(message="timeout", request=None) from e

            choice = resp.choices[0]
            text = (choice.message.content or "").strip()
            usage = resp.usage
            tokens_in = usage.prompt_tokens if usage else 0
            tokens_out = usage.completion_tokens if usage else 0
            cost = _calc_cost(model, tokens_in, tokens_out)

            log.info(
                "llm.chat",
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=round(cost, 5),
                user_hash=user_hash[:8] if user_hash else None,
                finish=choice.finish_reason,
            )

            return LLMResult(
                text=text,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                raw=resp,
            )

    raise RuntimeError(f"chat retries exhausted: {last_error}")


async def json_chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1500,
    user_hash: str | None = None,
    schema_hint: str | None = None,
    timeout: float = 60.0,
) -> tuple[dict, LLMResult]:
    """Variant that asks for and parses JSON. Returns (parsed_dict, full_result)."""
    if schema_hint:
        # Inject a system-style hint without overwriting existing system msg
        msgs: list[dict[str, Any]] = list(messages)
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = {**msgs[0], "content": msgs[0]["content"] + "\n\nReturn ONLY JSON. " + schema_hint}
        else:
            msgs.insert(0, {"role": "system", "content": "Return ONLY JSON. " + schema_hint})
    else:
        msgs = messages

    result = await chat(
        msgs,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        user_hash=user_hash,
        timeout=timeout,
    )
    try:
        parsed = json.loads(result.text)
        return parsed, result
    except json.JSONDecodeError:
        log.warning("llm.json_parse_failed", text_preview=result.text[:200])
        return {}, result


async def vision_chat(
    user_text: str,
    image_data_url: str,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 2000,
    user_hash: str | None = None,
) -> LLMResult:
    """Vision call: pass an image (data URL) plus optional text prompt."""
    settings = get_settings()
    model = model or settings.vision_model
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ],
    })
    return await chat(
        msgs,
        model=model,
        temperature=0.0,
        max_tokens=max_tokens,
        user_hash=user_hash,
    )


async def moderate(text: str) -> dict:
    """Run OpenAI moderation. Returns {flagged: bool, categories: {...}}."""
    client = _get_client()
    try:
        resp = await client.moderations.create(
            model="omni-moderation-latest",
            input=text[:8000],
        )
        r = resp.results[0]
        return {
            "flagged": r.flagged,
            "categories": r.categories.model_dump() if hasattr(r.categories, "model_dump") else dict(r.categories),
        }
    except Exception as e:
        log.warning("llm.moderation_failed", error=str(e))
        return {"flagged": False, "categories": {}, "error": str(e)}


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
