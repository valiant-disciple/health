"""
Day 11 tests — DSPy MIPROv2 optimised prompts.

Covers:
  - Signatures are defined with correct fields
  - Programs instantiate and expose correct predictors
  - Loader returns uncompiled program when no JSON exists
  - Loader returns compiled program when a JSON file is present
  - reset_programs() clears the singletons
  - Metric functions score correctly
  - interpret router calls get_interpret_program() (not raw OpenAI)
  - chat router calls get_chat_context_program() when memories are non-empty
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# 1. Signature field definitions
# DSPy 3.x registers fields via its metaclass; check .input_fields / .output_fields
# ---------------------------------------------------------------------------

class TestLabInterpretSignature:
    def test_has_patient_context_field(self):
        from dspy_programs.signatures import LabInterpretSignature
        assert "patient_context" in LabInterpretSignature.input_fields

    def test_has_lab_results_field(self):
        from dspy_programs.signatures import LabInterpretSignature
        assert "lab_results" in LabInterpretSignature.input_fields

    def test_has_interpretation_field(self):
        from dspy_programs.signatures import LabInterpretSignature
        assert "interpretation" in LabInterpretSignature.output_fields

    def test_docstring_mentions_json(self):
        from dspy_programs.signatures import LabInterpretSignature
        assert "JSON" in (LabInterpretSignature.__doc__ or "")

    def test_docstring_no_diagnosis(self):
        from dspy_programs.signatures import LabInterpretSignature
        assert "diagnose" in (LabInterpretSignature.__doc__ or "").lower()


class TestChatContextSignature:
    def test_has_memories_field(self):
        from dspy_programs.signatures import ChatContextSignature
        assert "memories" in ChatContextSignature.input_fields

    def test_has_question_field(self):
        from dspy_programs.signatures import ChatContextSignature
        assert "question" in ChatContextSignature.input_fields

    def test_has_focused_context_field(self):
        from dspy_programs.signatures import ChatContextSignature
        assert "focused_context" in ChatContextSignature.output_fields

    def test_docstring_mentions_distil_or_focused(self):
        from dspy_programs.signatures import ChatContextSignature
        doc = (ChatContextSignature.__doc__ or "").lower()
        assert "distil" in doc or "distill" in doc or "focused" in doc


# ---------------------------------------------------------------------------
# 2. Programs instantiate correctly
# ---------------------------------------------------------------------------

class TestLabInterpretProgram:
    def test_has_interpret_predictor(self):
        from dspy_programs.programs import LabInterpretProgram
        prog = LabInterpretProgram()
        assert hasattr(prog, "interpret")

    def test_forward_calls_interpret(self):
        from dspy_programs.programs import LabInterpretProgram
        prog = LabInterpretProgram()
        mock_pred = MagicMock(return_value=MagicMock(interpretation="{}"))
        prog.interpret = mock_pred
        prog.forward(patient_context="ctx", lab_results="labs")
        mock_pred.assert_called_once_with(patient_context="ctx", lab_results="labs")


class TestChatContextProgram:
    def test_has_refine_predictor(self):
        from dspy_programs.programs import ChatContextProgram
        prog = ChatContextProgram()
        assert hasattr(prog, "refine")

    def test_forward_calls_refine(self):
        from dspy_programs.programs import ChatContextProgram
        prog = ChatContextProgram()
        mock_pred = MagicMock(return_value=MagicMock(focused_context="summary"))
        prog.refine = mock_pred
        prog.forward(memories="mem", question="q")
        mock_pred.assert_called_once_with(memories="mem", question="q")


# ---------------------------------------------------------------------------
# 3. Loader — uncompiled path
# ---------------------------------------------------------------------------

class TestLoaderUncompiled:
    def setup_method(self):
        from dspy_programs import loader
        loader.reset_programs()

    def test_get_interpret_program_returns_instance(self):
        from dspy_programs import loader
        from dspy_programs.programs import LabInterpretProgram
        with patch("dspy_programs.loader._configure_dspy"):
            prog = loader.get_interpret_program()
        assert isinstance(prog, LabInterpretProgram)

    def test_get_interpret_program_is_singleton(self):
        from dspy_programs import loader
        with patch("dspy_programs.loader._configure_dspy"):
            p1 = loader.get_interpret_program()
            p2 = loader.get_interpret_program()
        assert p1 is p2

    def test_get_chat_context_program_returns_instance(self):
        from dspy_programs import loader
        from dspy_programs.programs import ChatContextProgram
        with patch("dspy_programs.loader._configure_dspy"):
            prog = loader.get_chat_context_program()
        assert isinstance(prog, ChatContextProgram)

    def test_get_chat_context_program_is_singleton(self):
        from dspy_programs import loader
        with patch("dspy_programs.loader._configure_dspy"):
            p1 = loader.get_chat_context_program()
            p2 = loader.get_chat_context_program()
        assert p1 is p2

    def test_reset_clears_interpret(self):
        from dspy_programs import loader
        with patch("dspy_programs.loader._configure_dspy"):
            p1 = loader.get_interpret_program()
        loader.reset_programs()
        with patch("dspy_programs.loader._configure_dspy"):
            p2 = loader.get_interpret_program()
        assert p1 is not p2

    def test_reset_clears_chat_context(self):
        from dspy_programs import loader
        with patch("dspy_programs.loader._configure_dspy"):
            p1 = loader.get_chat_context_program()
        loader.reset_programs()
        with patch("dspy_programs.loader._configure_dspy"):
            p2 = loader.get_chat_context_program()
        assert p1 is not p2


# ---------------------------------------------------------------------------
# 4. Loader — compiled path
# ---------------------------------------------------------------------------

class TestLoaderCompiled:
    def setup_method(self):
        from dspy_programs import loader
        loader.reset_programs()

    def test_loads_compiled_weights_when_file_exists(self, tmp_path):
        from dspy_programs import loader
        compiled_file = tmp_path / "interpret.json"
        compiled_file.write_text("{}")

        with patch("dspy_programs.loader._configure_dspy"), \
             patch("dspy_programs.loader.COMPILED_DIR", tmp_path):
            prog = loader.get_interpret_program()

        assert prog is not None

    def test_load_failure_is_graceful(self, tmp_path):
        """If prog.load() raises, fall through to uncompiled — no exception surfaced."""
        from dspy_programs import loader
        from dspy_programs.programs import LabInterpretProgram

        compiled_file = tmp_path / "interpret.json"
        compiled_file.write_text("{}")

        with patch("dspy_programs.loader._configure_dspy"), \
             patch("dspy_programs.loader.COMPILED_DIR", tmp_path), \
             patch.object(LabInterpretProgram, "load", side_effect=Exception("bad weights")):
            prog = loader.get_interpret_program()  # must not raise

        assert prog is not None

    def test_chat_context_compiled_path(self, tmp_path):
        from dspy_programs import loader
        compiled_file = tmp_path / "chat_context.json"
        compiled_file.write_text("{}")

        with patch("dspy_programs.loader._configure_dspy"), \
             patch("dspy_programs.loader.COMPILED_DIR", tmp_path):
            prog = loader.get_chat_context_program()

        assert prog is not None


# ---------------------------------------------------------------------------
# 5. Metric functions
# ---------------------------------------------------------------------------

class TestInterpretMetric:
    def _metric(self):
        from dspy_programs.optimize import _interpret_metric
        return _interpret_metric

    def _ex(self, lab_results="CBC"):
        ex = MagicMock()
        ex.lab_results = lab_results
        return ex

    def _pred(self, interpretation_str):
        pred = MagicMock()
        pred.interpretation = interpretation_str
        return pred

    def test_valid_json_with_all_keys_scores_high(self):
        payload = {
            "summary": "ok",
            "key_findings": [
                {
                    "loinc": "718-7", "name": "Hemoglobin", "value": "13.5",
                    "status": "normal", "explanation": "within range",
                    "trend": "stable", "previous_value": None, "previous_date": None,
                }
            ],
            "dietary_suggestions": [],
            "lifestyle_suggestions": [],
            "drug_nutrient_flags": [],
            "discuss_with_doctor": [],
            "context_used": "patient history",
        }
        score = self._metric()(self._ex(), self._pred(json.dumps(payload)))
        assert score >= 0.8

    def test_invalid_json_scores_zero(self):
        score = self._metric()(self._ex(), self._pred("not json"))
        assert score == 0.0

    def test_missing_required_keys_reduces_score(self):
        partial = {"summary": "ok", "key_findings": []}
        score = self._metric()(self._ex(), self._pred(json.dumps(partial)))
        assert 0.0 < score < 1.0

    def test_critical_finding_without_discuss_with_doctor_penalised(self):
        base = {
            "summary": "critical",
            "key_findings": [
                {
                    "loinc": "2345-7", "name": "Glucose", "value": "600",
                    "status": "critical", "explanation": "very high",
                    "trend": "up", "previous_value": None, "previous_date": None,
                }
            ],
            "dietary_suggestions": [],
            "lifestyle_suggestions": [],
            "drug_nutrient_flags": [],
            "discuss_with_doctor": [],
            "context_used": "x",
        }
        with_doctor = {**base, "discuss_with_doctor": ["See your doctor urgently"]}
        score_with = self._metric()(self._ex(), self._pred(json.dumps(with_doctor)))
        score_without = self._metric()(self._ex(), self._pred(json.dumps(base)))
        assert score_with > score_without


class TestChatContextMetric:
    def _metric(self):
        from dspy_programs.optimize import _chat_context_metric
        return _chat_context_metric

    def _ex(self):
        ex = MagicMock()
        ex.memories = "Hemoglobin was 11.5 g/dL on 2024-01-10. Prefers low-sugar diet."
        ex.question = "What does my low iron mean?"
        return ex

    def _pred(self, focused_context):
        pred = MagicMock()
        pred.focused_context = focused_context
        return pred

    def test_concise_specific_response_scores_high(self):
        ctx = (
            "Hemoglobin was 11.5 g/dL on 2024-01-10, indicating mild anaemia. "
            "Iron-related findings are relevant to your question about low iron."
        )
        score = self._metric()(self._ex(), self._pred(ctx))
        assert score >= 0.6

    def test_empty_response_scores_zero(self):
        score = self._metric()(self._ex(), self._pred(""))
        assert score == 0.0

    def test_very_long_response_penalised(self):
        short_ctx = "Hemoglobin was 11.5 g/dL on 2024-01-10."
        long_ctx = "word " * 200
        score_short = self._metric()(self._ex(), self._pred(short_ctx))
        score_long = self._metric()(self._ex(), self._pred(long_ctx))
        assert score_short >= score_long


# ---------------------------------------------------------------------------
# 6. interpret router uses DSPy program (not raw OpenAI)
# ---------------------------------------------------------------------------

class TestInterpretRouterUsesDSPy:
    def setup_method(self):
        from dspy_programs import loader
        loader.reset_programs()

    def test_interpret_calls_dspy_program(self):
        """Router must call get_interpret_program() and use result.interpretation."""
        interp_json = json.dumps({
            "summary": "ok",
            "key_findings": [],
            "dietary_suggestions": [],
            "lifestyle_suggestions": [],
            "drug_nutrient_flags": [],
            "discuss_with_doctor": [],
            "context_used": "test",
        })
        mock_result = MagicMock()
        mock_result.interpretation = interp_json
        mock_program = MagicMock(return_value=mock_result)

        with patch("routers.interpret.get_interpret_program", return_value=mock_program), \
             patch("routers.interpret.get_lab_results_for_report", new_callable=AsyncMock,
                   return_value=[{"biomarker_code": "718-7", "value_numeric": 13.5}]), \
             patch("routers.interpret.assemble_patient_artifact", new_callable=AsyncMock,
                   return_value="patient context"), \
             patch("routers.interpret.run_guardrails", new_callable=AsyncMock,
                   return_value=(interp_json, True, [])), \
             patch("routers.interpret.extract_and_store_facts", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.interpret as interpret_mod

            app = FastAPI()
            app.include_router(interpret_mod.router, prefix="/interpret")
            client = TestClient(app)

            resp = client.post(
                "/interpret/report",
                json={"user_id": "u1", "report_id": "r1"},
                headers={"X-User-Id": "u1"},
            )

        assert resp.status_code == 200
        assert "interpretation" in resp.json()
        mock_program.assert_called_once()


# ---------------------------------------------------------------------------
# 7. chat router applies context refinement when memories are non-empty
# ---------------------------------------------------------------------------

class TestChatRouterContextRefinement:
    def setup_method(self):
        from dspy_programs import loader
        loader.reset_programs()

    def test_context_program_called_when_memories_present(self):
        """When memories are non-empty, get_chat_context_program() should be called."""
        mock_ctx_result = MagicMock()
        mock_ctx_result.focused_context = "Relevant: Hemoglobin was 11.5 on 2024-01-10."
        mock_ctx_prog = MagicMock(return_value=mock_ctx_result)

        async def _fake_agent(**kwargs):
            yield "response text"

        with patch("routers.chat.get_chat_context_program", return_value=mock_ctx_prog), \
             patch("routers.chat.get_relevant_memories", new_callable=AsyncMock,
                   return_value="raw memories text"), \
             patch("routers.chat._load_conversation_history", new_callable=AsyncMock,
                   return_value=[]), \
             patch("routers.chat.scan_user_input", new_callable=AsyncMock,
                   return_value=("my iron is low", True)), \
             patch("routers.chat.apply_dialog_rails", new_callable=AsyncMock,
                   return_value=("my iron is low", True)), \
             patch("routers.chat.run_health_agent", return_value=_fake_agent(
                 user_id="u1", message="my iron is low", conversation_id="c1",
                 report_id=None, memories="Relevant: Hemoglobin was 11.5 on 2024-01-10.",
                 conversation_history=[],
             )), \
             patch("routers.chat.update_user_memory", new_callable=AsyncMock), \
             patch("routers.chat._persist_messages", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.chat as chat_mod

            app = FastAPI()
            app.include_router(chat_mod.router, prefix="/chat")
            client = TestClient(app)

            client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "my iron is low"},
                headers={"X-User-Id": "u1"},
            )

        mock_ctx_prog.assert_called_once()

    def test_context_program_skipped_when_no_memories(self):
        """When memories are empty/falsy, context program should NOT be called."""
        mock_ctx_prog = MagicMock()

        async def _fake_agent(**kwargs):
            yield "hi"

        with patch("routers.chat.get_chat_context_program", return_value=mock_ctx_prog), \
             patch("routers.chat.get_relevant_memories", new_callable=AsyncMock,
                   return_value=""), \
             patch("routers.chat._load_conversation_history", new_callable=AsyncMock,
                   return_value=[]), \
             patch("routers.chat.scan_user_input", new_callable=AsyncMock,
                   return_value=("hello", True)), \
             patch("routers.chat.apply_dialog_rails", new_callable=AsyncMock,
                   return_value=("hello", True)), \
             patch("routers.chat.run_health_agent", return_value=_fake_agent(
                 user_id="u1", message="hello", conversation_id="c1",
                 report_id=None, memories="", conversation_history=[],
             )), \
             patch("routers.chat.update_user_memory", new_callable=AsyncMock), \
             patch("routers.chat._persist_messages", new_callable=AsyncMock):

            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            import routers.chat as chat_mod

            app = FastAPI()
            app.include_router(chat_mod.router, prefix="/chat")
            client = TestClient(app)

            client.post(
                "/chat/",
                json={"user_id": "u1", "conversation_id": "c1", "message": "hello"},
                headers={"X-User-Id": "u1"},
            )

        mock_ctx_prog.assert_not_called()
