from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import anthropic
import structlog

from config import settings
from services.context import assemble_patient_artifact
from services.ocr import get_lab_results_for_report
from services.guardrails import run_guardrails
from services.memory import extract_and_store_facts
from prompts.interpret import INTERPRET_SYSTEM_PROMPT, build_interpret_user_prompt

log = structlog.get_logger()
router = APIRouter()
claude = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


class InterpretRequest(BaseModel):
    user_id: str
    report_id: str


@router.post("/report")
async def interpret_report(
    req: InterpretRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
):
    # Verify caller matches claimed user_id (JWT validated by middleware)
    if x_user_id != req.user_id:
        raise HTTPException(403, "User ID mismatch")

    log.info("interpret_report.start", user_id=req.user_id, report_id=req.report_id)

    # 1. Fetch structured lab results (post-OCR)
    lab_results = await get_lab_results_for_report(req.report_id, req.user_id)
    if not lab_results:
        raise HTTPException(404, "Report not found or not yet processed")

    # 2. Assemble patient artifact (≤3k tokens)
    context = await assemble_patient_artifact(req.user_id, focus="lab_interpretation")

    # 3. Build prompt and call Claude
    user_prompt = build_interpret_user_prompt(context=context, lab_results=lab_results)

    message = await claude.messages.create(
        model=settings.PRIMARY_MODEL,
        max_tokens=4096,
        system=INTERPRET_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_output = message.content[0].text  # type: ignore[index]

    # 4. Guardrails check
    safe_output, is_safe, critical_flags = await run_guardrails(
        user_input=user_prompt,
        llm_output=raw_output,
        lab_results=lab_results,
    )
    if not is_safe:
        log.warning("interpret_report.guardrail_blocked", user_id=req.user_id)
        raise HTTPException(422, "Response did not pass safety check")

    # 5. Parse JSON interpretation
    import json, re
    json_match = re.search(r"\{.*\}", safe_output, re.DOTALL)
    if not json_match:
        raise HTTPException(500, "Could not parse interpretation JSON")
    interpretation = json.loads(json_match.group())

    # 6. Async: extract facts to Graphiti (fire and forget)
    import asyncio
    asyncio.create_task(extract_and_store_facts(req.user_id, interpretation, req.report_id))

    log.info("interpret_report.done", user_id=req.user_id, critical_count=len(critical_flags))
    return {"interpretation": interpretation, "critical_flags": critical_flags}
