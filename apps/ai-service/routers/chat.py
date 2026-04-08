from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import structlog
import json

from config import settings
from agents.health_agent import run_health_agent
from services.guardrails import scan_user_input
from services.memory import get_relevant_memories, update_user_memory

log = structlog.get_logger()
router = APIRouter()


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

    # L1 guardrail: scan input before anything
    sanitized_input, input_safe = await scan_user_input(req.message)
    if not input_safe:
        raise HTTPException(400, "Message blocked by safety filter")

    # Retrieve relevant memories before building agent state
    memories = await get_relevant_memories(req.user_id, sanitized_input)

    async def generate():
        full_response = ""
        async for chunk in run_health_agent(
            user_id=req.user_id,
            message=sanitized_input,
            conversation_id=req.conversation_id,
            report_id=req.report_id,
            memories=memories,
        ):
            full_response += chunk
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

        yield "data: [DONE]\n\n"

        # Update memory asynchronously after response
        import asyncio
        asyncio.create_task(
            update_user_memory(
                req.user_id,
                [
                    {"role": "user", "content": sanitized_input},
                    {"role": "assistant", "content": full_response},
                ],
            )
        )

    return StreamingResponse(generate(), media_type="text/event-stream")
