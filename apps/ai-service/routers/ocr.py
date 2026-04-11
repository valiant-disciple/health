import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

from services.ocr import process_lab_report

log = structlog.get_logger()
router = APIRouter()


class ProcessRequest(BaseModel):
    report_id: str
    user_id: str
    file_path: str


@router.post("/process", status_code=202)
async def trigger_ocr(req: ProcessRequest):
    """
    Trigger OCR processing for an uploaded lab report.
    Returns immediately — processing continues in the background.
    Poll GET /reports/{id} for status updates.
    """
    log.info("ocr.process_requested", report_id=req.report_id, user_id=req.user_id)

    # Fire and forget — background task so the 202 returns instantly
    asyncio.create_task(
        process_lab_report(req.report_id, req.user_id, req.file_path)
    )

    return {"status": "accepted", "report_id": req.report_id}
