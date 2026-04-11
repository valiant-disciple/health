import asyncio

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import structlog
import json

from agents.health_agent import run_health_agent
from services.db import get_supabase
from services.guardrails import scan_user_input, apply_dialog_rails, scan_llm_output
from services.memory import get_relevant_memories, update_user_memory
from services.rate_limit import check_rate_limit
from dspy_programs import get_chat_context_program

log = structlog.get_logger()
router = APIRouter()

# Max prior turns to load — keeps context window manageable
MAX_HISTORY_TURNS = 10


class ChatRequest(BaseModel):
    user_id: str
    conversation_id: str
    message: str
    report_id: str | None = None   # optional: lock context to a specific report


@router.post("/")
async def chat(
    req: ChatRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    if x_user_id != req.user_id:
        raise HTTPException(403)

    # Rate limit: 30 requests / 60 seconds per user
    check_rate_limit(req.user_id, "chat")

    # L1 guardrail: LLM Guard input scan
    sanitized_input, input_safe = await scan_user_input(req.message)
    if not input_safe:
        raise HTTPException(400, "Message blocked by safety filter")

    # L2 guardrail: NeMo dialog rails (topic gating, crisis routing)
    gated_input, dialog_allowed = await apply_dialog_rails(sanitized_input)
    if not dialog_allowed:
        # Return NeMo's response directly (may include emergency signposting)
        async def nemo_response():
            yield f"data: {json.dumps({'chunk': gated_input})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(nemo_response(), media_type="text/event-stream")

    # Load prior messages for session continuity (last MAX_HISTORY_TURNS turns)
    conversation_history = await _load_conversation_history(req.conversation_id)

    # Retrieve relevant memories, then distil to focused context via DSPy
    memories = await get_relevant_memories(req.user_id, sanitized_input)
    if memories:
        try:
            loop = asyncio.get_event_loop()
            ctx_program = get_chat_context_program()
            ctx_result = await loop.run_in_executor(
                None,
                lambda: ctx_program(memories=memories, question=sanitized_input),
            )
            memories = ctx_result.focused_context or memories
        except Exception as e:
            log.warning("chat.context_refine_failed", error=str(e), exc_info=True)

    async def generate():
        full_response = ""
        try:
            async for chunk in run_health_agent(
                user_id=req.user_id,
                message=sanitized_input,
                conversation_id=req.conversation_id,
                report_id=req.report_id,
                memories=memories,
                conversation_history=conversation_history,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            log.error("chat.agent_failed", user_id=req.user_id, error=str(e), exc_info=True)
            yield f"data: {json.dumps({'chunk': 'Sorry, I encountered an error. Please try again.', 'error': True})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # L3 guardrail: scan full response for PHI leakage / harmful output
        safe_response, output_safe = await scan_llm_output(sanitized_input, full_response)
        if not output_safe:
            log.warning("chat.l3_output_blocked", user_id=req.user_id)
            safe_response = (
                "I'm not able to send that response. Please rephrase your question "
                "or speak with a healthcare professional."
            )
            # Send a replacement chunk so the client receives something
            yield f"data: {json.dumps({'chunk': safe_response, 'filtered': True})}\n\n"

        yield "data: [DONE]\n\n"

        final_response = safe_response if not output_safe else full_response
        turn_messages = [
            {"role": "user",      "content": sanitized_input},
            {"role": "assistant", "content": final_response},
        ]
        # Persist messages to DB (session continuity)
        asyncio.create_task(
            _persist_messages(req.conversation_id, req.user_id, turn_messages)
        )
        # Update Mem0 with the conversation turn
        asyncio.create_task(update_user_memory(req.user_id, turn_messages))

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _load_conversation_history(conversation_id: str) -> list[dict]:
    """Load the last MAX_HISTORY_TURNS messages for session continuity."""
    try:
        db = await get_supabase()
        res = await db.table("messages") \
            .select("role,content") \
            .eq("conversation_id", conversation_id) \
            .order("created_at", desc=True) \
            .limit(MAX_HISTORY_TURNS * 2) \
            .execute()
        messages = res.data or []
        # Reverse to chronological order (we fetched newest-first)
        messages.reverse()
        return [{"role": m["role"], "content": m["content"]} for m in messages]
    except Exception as e:
        log.warning("chat.history_load_failed", conversation_id=conversation_id, error=str(e), exc_info=True)
        return []


async def _persist_messages(
    conversation_id: str,
    user_id: str,
    messages: list[dict],
) -> None:
    """Save a list of messages to the messages table."""
    try:
        db = await get_supabase()
        rows = [
            {
                "conversation_id": conversation_id,
                "user_id":         user_id,
                "role":            m["role"],
                "content":         m["content"],
            }
            for m in messages
        ]
        await db.table("messages").insert(rows).execute()
    except Exception as e:
        log.error("chat.persist_failed", conversation_id=conversation_id, error=str(e), exc_info=True)
