from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import structlog

from services.memory import extract_and_store_facts

log = structlog.get_logger()
router = APIRouter()


class ExtractRequest(BaseModel):
    user_id: str
    report_id: str
    interpretation: dict


@router.post("/facts")
async def extract_facts(
    req: ExtractRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    """Called by Inngest after report interpretation to store facts in Graphiti."""
    if x_user_id != req.user_id:
        raise HTTPException(403)

    await extract_and_store_facts(req.user_id, req.interpretation, req.report_id)
    return {"status": "ok"}
