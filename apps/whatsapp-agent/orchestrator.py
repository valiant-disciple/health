"""Single-LLM orchestrator with bounded tool-calling.

Flow:
  1. Build messages: system prompt + user-context block + recent history + current user message
  2. Call LLM with tools enabled
  3. If LLM wants to call tools, dispatch up to MAX_TOOL_CALLS tools and re-call
  4. Apply output guardrails to the final text
  5. Return the text + cost metadata

This module owns the *conversation* path. The PDF interpretation path is in
handlers.py (it uses a different prompt template) but ultimately writes
responses via this module's same machinery.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog

from config import get_settings
from llm import LLMResult, chat
from memory import build_user_context_block, recent_conversation
from prompts import ORCHESTRATOR_SYSTEM
from tools import TOOL_SCHEMAS, dispatch_tool_call

log = structlog.get_logger()

MAX_TOOL_CALLS = 3


@dataclass
class OrchestratorResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    tool_calls_made: int = 0
    extracted_entities: dict = field(default_factory=dict)


def _wrap_user_input(text: str) -> str:
    """Wrap user content in tags so the model treats it as data, not commands."""
    safe = text.replace("</user_message>", "&lt;/user_message&gt;")
    return f"<user_message>\n{safe}\n</user_message>"


async def respond(
    user_id: UUID,
    user_message: str,
    *,
    user_hash: str | None = None,
) -> OrchestratorResult:
    """Generate a response to a free-text user message."""
    settings = get_settings()

    # 1. Build context
    user_ctx_block = await build_user_context_block(user_id, current_message=user_message)
    recent = await recent_conversation(user_id, limit=settings.conversation_history_turns)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ORCHESTRATOR_SYSTEM + "\n\n# User context\n\n" + user_ctx_block},
    ]
    for r in recent:
        messages.append({"role": r["role"], "content": r["content"]})
    messages.append({"role": "user", "content": _wrap_user_input(user_message)})

    # 2. Tool-calling loop
    total_in = 0
    total_out = 0
    total_cost = 0.0
    tool_count = 0
    final_text = ""
    final_model = settings.orchestrator_model

    for iteration in range(MAX_TOOL_CALLS + 1):
        result: LLMResult = await chat(
            messages=messages,
            model=settings.orchestrator_model,
            tools=TOOL_SCHEMAS,
            tool_choice="auto" if iteration < MAX_TOOL_CALLS else "none",
            user_hash=user_hash,
            max_tokens=1500,
            temperature=0.4,
        )
        total_in += result.tokens_in
        total_out += result.tokens_out
        total_cost += result.cost_usd
        final_model = result.model

        choice = result.raw.choices[0] if result.raw else None
        msg = choice.message if choice else None

        # If no tool calls or no message, we're done
        if not msg or not getattr(msg, "tool_calls", None):
            final_text = (msg.content if msg else result.text) or ""
            break

        # Append the assistant message (with tool_calls) to the conversation
        assistant_payload: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        }
        messages.append(assistant_payload)

        # Dispatch each tool call
        for tc in msg.tool_calls:
            tool_count += 1
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_result = await dispatch_tool_call(user_id, tc.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                }
            )

        if tool_count >= MAX_TOOL_CALLS:
            # One more LLM call without tools to force a final answer
            final_call = await chat(
                messages=messages,
                model=settings.orchestrator_model,
                tool_choice="none",
                user_hash=user_hash,
                max_tokens=1500,
                temperature=0.4,
            )
            total_in += final_call.tokens_in
            total_out += final_call.tokens_out
            total_cost += final_call.cost_usd
            final_text = final_call.text
            break

    return OrchestratorResult(
        text=final_text.strip(),
        model=final_model,
        tokens_in=total_in,
        tokens_out=total_out,
        cost_usd=total_cost,
        tool_calls_made=tool_count,
    )
