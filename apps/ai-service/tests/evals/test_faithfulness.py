"""
DeepEval faithfulness + hallucination evals for the lab interpretation pipeline.

These tests call the DSPy interpret program with real LLM calls and measure:
  - Faithfulness: output claims are grounded in the provided lab data
  - Answer Relevancy: output actually addresses the patient's lab results
  - No hallucination: output does not introduce false medical claims

Threshold: faithfulness >= 0.85, answer_relevancy >= 0.80
"""
from __future__ import annotations

import json
import os
import pytest

from deepeval import assert_test
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric, HallucinationMetric
from deepeval.test_case import LLMTestCase

from dspy_programs import get_interpret_program
from dspy_programs.loader import reset_programs


FAITHFULNESS_THRESHOLD = 0.85
RELEVANCY_THRESHOLD = 0.80
HALLUCINATION_THRESHOLD = 0.30  # lower is better — fail if hallucination score > this


def _run_interpret(case: dict) -> str:
    """Run the DSPy interpret program and return raw output string."""
    reset_programs()
    program = get_interpret_program()
    result = program(
        patient_context=case["patient_context"],
        lab_results=case["lab_results"],
    )
    return result.interpretation or ""


def _build_retrieval_context(case: dict) -> list[str]:
    """Build the 'retrieval context' from the lab results + patient context."""
    lab_data = json.loads(case["lab_results"])
    ctx = [case["patient_context"]]
    for lab in lab_data:
        ctx.append(
            f"{lab['name']} ({lab['loinc']}): {lab['value']} {lab['unit']} "
            f"[ref: {lab['reference_range']}] status={lab['status']}"
        )
    return ctx


def _make_faithfulness_test(case: dict):
    output = _run_interpret(case)
    retrieval_context = _build_retrieval_context(case)

    test_case = LLMTestCase(
        input=f"Interpret labs for: {case['patient_context'][:100]}",
        actual_output=output,
        retrieval_context=retrieval_context,
    )

    metric = FaithfulnessMetric(
        threshold=FAITHFULNESS_THRESHOLD,
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        include_reason=True,
    )

    assert_test(test_case, [metric])


def _make_relevancy_test(case: dict):
    output = _run_interpret(case)

    test_case = LLMTestCase(
        input=case["lab_results"],
        actual_output=output,
    )

    metric = AnswerRelevancyMetric(
        threshold=RELEVANCY_THRESHOLD,
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        include_reason=True,
    )

    assert_test(test_case, [metric])


def _make_hallucination_test(case: dict):
    output = _run_interpret(case)
    context = _build_retrieval_context(case)

    test_case = LLMTestCase(
        input=case["lab_results"],
        actual_output=output,
        context=context,
    )

    metric = HallucinationMetric(
        threshold=HALLUCINATION_THRESHOLD,
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        include_reason=True,
    )

    assert_test(test_case, [metric])


# ---------------------------------------------------------------------------
# Parametrised test functions (one per case, clearly named in CI output)
# ---------------------------------------------------------------------------

from tests.evals.conftest import INTERPRET_CASES


@pytest.mark.parametrize("case", INTERPRET_CASES, ids=[c["id"] for c in INTERPRET_CASES])
def test_faithfulness(case):
    """Interpretation output is grounded in provided lab data — no fabricated values."""
    _make_faithfulness_test(case)


@pytest.mark.parametrize("case", INTERPRET_CASES, ids=[c["id"] for c in INTERPRET_CASES])
def test_answer_relevancy(case):
    """Interpretation output actually addresses the patient's lab results."""
    _make_relevancy_test(case)


@pytest.mark.parametrize("case", INTERPRET_CASES, ids=[c["id"] for c in INTERPRET_CASES])
def test_hallucination(case):
    """Interpretation output does not introduce false medical claims."""
    _make_hallucination_test(case)
