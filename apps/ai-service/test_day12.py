"""
Day 12 tests — DeepEval/RAGAS pipeline + Langfuse tracing.

These are unit tests (no real LLM calls, no real Langfuse).
They verify:
  - Tracing module initialises correctly
  - Tracing no-ops gracefully when keys are missing
  - trace_generation() passes correct params to the trace object
  - flush() is safe in all states
  - Agent wires Langfuse callback with correct session/user metadata
  - Eval conftest has well-formed test case structure
  - RAGAS dataset builder produces the correct schema
  - DeepEval test cases have required fields
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ---------------------------------------------------------------------------
# 1. Tracing module — no-op mode
# ---------------------------------------------------------------------------

class TestTracingNoOp:
    def setup_method(self):
        from services import tracing
        tracing.reset()

    def test_create_trace_none_when_no_keys(self):
        from services import tracing
        with patch.object(tracing.settings, "LANGFUSE_PUBLIC_KEY", ""), \
             patch.object(tracing.settings, "LANGFUSE_SECRET_KEY", ""):
            assert tracing.create_trace("test") is None

    def test_trace_generation_none_trace_no_raise(self):
        from services import tracing
        tracing.trace_generation(None, "gen", "gpt-4o", "in", "out")  # must not raise

    def test_get_callback_none_when_no_keys(self):
        from services import tracing
        with patch.object(tracing.settings, "LANGFUSE_PUBLIC_KEY", ""), \
             patch.object(tracing.settings, "LANGFUSE_SECRET_KEY", ""):
            assert tracing.get_langfuse_callback() is None

    def test_flush_no_raise_when_no_langfuse(self):
        from services import tracing
        tracing._langfuse = None
        tracing.flush()  # must not raise

    def test_reset_sets_none(self):
        from services import tracing
        tracing._langfuse = MagicMock()
        tracing.reset()
        assert tracing._langfuse is None


# ---------------------------------------------------------------------------
# 2. Tracing module — with mock Langfuse
# ---------------------------------------------------------------------------

class TestTracingWithMock:
    def setup_method(self):
        from services import tracing
        tracing.reset()

    def test_trace_generation_calls_trace_dot_generation(self):
        from services import tracing
        mock_trace = MagicMock()
        tracing.trace_generation(
            trace=mock_trace,
            name="interpret",
            model="gpt-4o",
            input_="patient context",
            output='{"summary": "ok"}',
            usage={"prompt_tokens": 100, "completion_tokens": 200},
            metadata={"report_id": "r1"},
        )
        mock_trace.generation.assert_called_once()
        kwargs = mock_trace.generation.call_args.kwargs
        assert kwargs["name"] == "interpret"
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["output"] == '{"summary": "ok"}'
        assert kwargs["usage"] == {"prompt_tokens": 100, "completion_tokens": 200}

    def test_flush_calls_langfuse_flush(self):
        from services import tracing
        mock_lf = MagicMock()
        tracing._langfuse = mock_lf
        tracing.flush()
        mock_lf.flush.assert_called_once()

    def test_flush_swallows_exception(self):
        from services import tracing
        mock_lf = MagicMock()
        mock_lf.flush.side_effect = Exception("connection refused")
        tracing._langfuse = mock_lf
        tracing.flush()  # must not raise

    def test_create_trace_swallows_exception(self):
        from services import tracing
        mock_lf = MagicMock()
        mock_lf.trace.side_effect = Exception("api error")
        tracing._langfuse = mock_lf
        # Inject the mock directly to bypass init
        with patch.object(tracing, "_get_langfuse", return_value=mock_lf):
            result = tracing.create_trace("test", user_id="u1")
        assert result is None


# ---------------------------------------------------------------------------
# 3. Agent Langfuse wiring
# ---------------------------------------------------------------------------

class TestAgentLangfuseWiring:
    @pytest.mark.asyncio
    async def test_langfuse_callback_attached_to_stream(self):
        mock_cb = MagicMock()
        mock_cb.session_id = None
        mock_cb.user_id = None

        captured = {}

        async def mock_astream_events(state, version, config=None):
            captured["config"] = config or {}
            return
            yield  # async generator

        from agents import health_agent
        with patch("agents.health_agent.get_langfuse_callback", return_value=mock_cb), \
             patch.object(health_agent, "get_graph") as mock_get_graph:

            mock_graph = MagicMock()
            mock_graph.astream_events = mock_astream_events
            mock_get_graph.return_value = mock_graph

            async for _ in health_agent.run_health_agent(
                user_id="user-abc",
                message="hello",
                conversation_id="conv-xyz",
                report_id=None,
                memories="",
            ):
                pass

        assert mock_cb in captured["config"].get("callbacks", [])
        assert mock_cb.session_id == "conv-xyz"
        assert mock_cb.user_id == "user-abc"

    @pytest.mark.asyncio
    async def test_no_callback_when_langfuse_returns_none(self):
        captured = {}

        async def mock_astream_events(state, version, config=None):
            captured["config"] = config or {}
            return
            yield

        from agents import health_agent
        with patch("agents.health_agent.get_langfuse_callback", return_value=None), \
             patch.object(health_agent, "get_graph") as mock_get_graph:

            mock_graph = MagicMock()
            mock_graph.astream_events = mock_astream_events
            mock_get_graph.return_value = mock_graph

            async for _ in health_agent.run_health_agent(
                user_id="u1",
                message="hi",
                conversation_id="c1",
                report_id=None,
                memories="",
            ):
                pass

        assert captured["config"].get("callbacks") == []


# ---------------------------------------------------------------------------
# 4. Eval conftest structure validation (no LLM calls)
# ---------------------------------------------------------------------------

class TestEvalConftest:
    def test_interpret_cases_have_required_keys(self):
        from tests.evals.conftest import INTERPRET_CASES
        required = {"id", "patient_context", "lab_results", "expected_keys",
                    "must_mention", "must_discuss_with_doctor"}
        for case in INTERPRET_CASES:
            missing = required - set(case.keys())
            assert not missing, f"Case {case.get('id')} missing keys: {missing}"

    def test_interpret_cases_lab_results_are_valid_json(self):
        from tests.evals.conftest import INTERPRET_CASES
        for case in INTERPRET_CASES:
            parsed = json.loads(case["lab_results"])
            assert isinstance(parsed, list)
            assert len(parsed) > 0

    def test_interpret_cases_lab_results_have_loinc(self):
        from tests.evals.conftest import INTERPRET_CASES
        for case in INTERPRET_CASES:
            for lab in json.loads(case["lab_results"]):
                assert "loinc" in lab
                assert "name" in lab
                assert "value" in lab
                assert "status" in lab

    def test_rag_cases_have_required_keys(self):
        from tests.evals.conftest import RAG_CASES
        required = {"id", "question", "ground_truth_contexts", "reference_answer"}
        for case in RAG_CASES:
            missing = required - set(case.keys())
            assert not missing, f"Case {case.get('id')} missing keys: {missing}"

    def test_rag_cases_have_multiple_ground_truth_contexts(self):
        from tests.evals.conftest import RAG_CASES
        for case in RAG_CASES:
            assert len(case["ground_truth_contexts"]) >= 2, (
                f"Case {case['id']} should have at least 2 ground truth contexts"
            )

    def test_at_least_three_interpret_cases(self):
        from tests.evals.conftest import INTERPRET_CASES
        assert len(INTERPRET_CASES) >= 3

    def test_at_least_three_rag_cases(self):
        from tests.evals.conftest import RAG_CASES
        assert len(RAG_CASES) >= 3


# ---------------------------------------------------------------------------
# 5. DeepEval test case structure (mock — no LLM calls)
# ---------------------------------------------------------------------------

class TestDeepEvalCaseStructure:
    def test_faithfulness_metric_can_be_instantiated(self):
        from deepeval.metrics import FaithfulnessMetric
        metric = FaithfulnessMetric(threshold=0.85, model="gpt-4o")
        assert metric.threshold == 0.85

    def test_answer_relevancy_metric_can_be_instantiated(self):
        from deepeval.metrics import AnswerRelevancyMetric
        metric = AnswerRelevancyMetric(threshold=0.80, model="gpt-4o")
        assert metric.threshold == 0.80

    def test_hallucination_metric_can_be_instantiated(self):
        from deepeval.metrics import HallucinationMetric
        metric = HallucinationMetric(threshold=0.30, model="gpt-4o")
        assert metric.threshold == 0.30

    def test_llm_test_case_fields(self):
        from deepeval.test_case import LLMTestCase
        tc = LLMTestCase(
            input="What does high glucose mean?",
            actual_output='{"summary": "glucose is high"}',
            retrieval_context=["Glucose > 100 mg/dL is elevated"],
        )
        assert tc.input == "What does high glucose mean?"
        assert tc.actual_output == '{"summary": "glucose is high"}'
        assert len(tc.retrieval_context) == 1


# ---------------------------------------------------------------------------
# 6. RAGAS dataset schema (mock — no LLM calls)
# ---------------------------------------------------------------------------

class TestRagasDatasetSchema:
    def test_dataset_has_correct_columns(self):
        from datasets import Dataset
        rows = [
            {
                "question": "What is creatinine?",
                "answer": "A kidney waste product.",
                "contexts": ["Creatinine is filtered by kidneys."],
                "ground_truth": "Creatinine is a waste product from muscle metabolism.",
                "ground_truths": ["Creatinine is a waste product from muscle metabolism."],
            }
        ]
        ds = Dataset.from_list(rows)
        assert "question" in ds.column_names
        assert "answer" in ds.column_names
        assert "contexts" in ds.column_names
        assert "ground_truth" in ds.column_names

    def test_ragas_cases_produce_correct_row_count(self):
        from tests.evals.conftest import RAG_CASES
        from datasets import Dataset

        rows = [
            {
                "question": c["question"],
                "answer": "mock answer",
                "contexts": c["ground_truth_contexts"],
                "ground_truth": c["reference_answer"],
                "ground_truths": [c["reference_answer"]],
            }
            for c in RAG_CASES
        ]
        ds = Dataset.from_list(rows)
        assert len(ds) == len(RAG_CASES)
