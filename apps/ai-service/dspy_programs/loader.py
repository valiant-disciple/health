"""
Singleton loader for compiled DSPy programs.

At startup:
  - If dspy_compiled/{name}.json exists → load the MIPROv2-optimised weights
    (instruction + few-shot demos).
  - Otherwise → use the uncompiled program (hand-written instructions,
    no few-shot examples). Still fully functional, just not optimised.

Programs are configured with a fast model for inference (gpt-4o-mini by default)
and the API key from settings.
"""
from __future__ import annotations

from pathlib import Path
import structlog

log = structlog.get_logger()

_interpret_program = None
_chat_context_program = None

COMPILED_DIR = Path(__file__).parent.parent / "dspy_compiled"


def _configure_dspy():
    """Configure DSPy LM from settings (idempotent)."""
    try:
        import dspy
        from config import settings
        lm = dspy.LM(
            f"openai/{settings.FAST_MODEL}",
            api_key=settings.OPENAI_API_KEY,
            cache=False,
        )
        dspy.configure(lm=lm)
    except Exception as e:
        log.warning("dspy.configure_failed", error=str(e))


def get_interpret_program():
    """Return the (possibly compiled) LabInterpretProgram singleton."""
    global _interpret_program
    if _interpret_program is not None:
        return _interpret_program

    _configure_dspy()

    from dspy_programs.programs import LabInterpretProgram
    prog = LabInterpretProgram()

    compiled_path = COMPILED_DIR / "interpret.json"
    if compiled_path.exists():
        try:
            prog.load(str(compiled_path))
            log.info("dspy.interpret_program_loaded", path=str(compiled_path))
        except Exception as e:
            log.warning("dspy.interpret_load_failed", error=str(e))
    else:
        log.info("dspy.interpret_program_uncompiled")

    _interpret_program = prog
    return _interpret_program


def get_chat_context_program():
    """Return the (possibly compiled) ChatContextProgram singleton."""
    global _chat_context_program
    if _chat_context_program is not None:
        return _chat_context_program

    _configure_dspy()

    from dspy_programs.programs import ChatContextProgram
    prog = ChatContextProgram()

    compiled_path = COMPILED_DIR / "chat_context.json"
    if compiled_path.exists():
        try:
            prog.load(str(compiled_path))
            log.info("dspy.chat_context_program_loaded", path=str(compiled_path))
        except Exception as e:
            log.warning("dspy.chat_context_load_failed", error=str(e))
    else:
        log.info("dspy.chat_context_program_uncompiled")

    _chat_context_program = prog
    return _chat_context_program


def reset_programs():
    """Reset singletons — used in tests and after recompilation."""
    global _interpret_program, _chat_context_program
    _interpret_program = None
    _chat_context_program = None
