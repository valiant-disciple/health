"""
DSPy Signature definitions for the two main LLM tasks.

Signatures describe the task contract: what goes in, what comes out, and
the high-level instruction in the docstring. MIPROv2 optimises the instruction
and selects few-shot examples; the field names and types stay fixed.
"""
from __future__ import annotations
import dspy


class LabInterpretSignature(dspy.Signature):
    """
    Interpret laboratory results for a specific patient using their full longitudinal
    health context. Return a structured JSON interpretation personalised to this patient —
    their conditions, medications, prior trends, and health goals.

    RULES:
    - Return ONLY valid JSON. No markdown fences, no preamble, no trailing text.
    - Every explanation must reference the patient's specific value, not generic text.
    - Every dietary suggestion must cite the specific lab finding that motivates it.
    - Flag drug-nutrient interactions based on the patient's actual medication list.
    - Never diagnose a condition — only explain what values mean and what might help.
    - Always include a discuss_with_doctor item for status = high | critical.
    """

    patient_context: str = dspy.InputField(
        desc="Patient demographics, active conditions, current medications, "
             "recent lab history, drug interactions, and health goals"
    )
    lab_results: str = dspy.InputField(
        desc="Structured lab results: LOINC code, test name, value, unit, "
             "reference range, flag (H/L/HH/LL), status (normal/high/low/critical)"
    )
    interpretation: str = dspy.OutputField(
        desc=(
            "Valid JSON with keys: summary, key_findings (list with loinc/name/value/"
            "status/explanation/trend/previous_value/previous_date), dietary_suggestions "
            "(category/suggestion/mechanism/foods/priority), lifestyle_suggestions, "
            "drug_nutrient_flags, discuss_with_doctor, context_used. "
            "No markdown. No prose outside the JSON object."
        )
    )


class ChatContextSignature(dspy.Signature):
    """
    Distill a patient's health memories and their current question into a concise,
    focused context summary. The summary should surface only the memories most
    relevant to answering this specific question, so the downstream health AI
    can give a personalised, evidence-based response without wading through
    irrelevant history.
    """

    memories: str = dspy.InputField(
        desc="The patient's stored health memories from prior conversations: "
             "lab findings, preferences, conditions they've mentioned, lifestyle factors"
    )
    question: str = dspy.InputField(
        desc="The patient's current health question or message"
    )
    focused_context: str = dspy.OutputField(
        desc="2-3 sentences that highlight only the most relevant prior memories "
             "for this specific question. Be specific — quote values and dates when available. "
             "Omit irrelevant memories entirely."
    )
