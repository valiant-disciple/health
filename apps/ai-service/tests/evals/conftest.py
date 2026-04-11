"""
Shared fixtures for the evaluation suite.

Synthetic test data only — no real patient records.
All LLM calls use the live API (evals job has the key injected).
"""
from __future__ import annotations

import json
import pytest

# ---------------------------------------------------------------------------
# Synthetic lab interpretation test cases
# Each case has: patient_context, lab_results, expected properties
# ---------------------------------------------------------------------------

INTERPRET_CASES = [
    {
        "id": "high_glucose_diabetic",
        "patient_context": (
            "Patient: 52-year-old male. Conditions: Type 2 diabetes (diagnosed 2019), "
            "hypertension. Medications: Metformin 1000mg twice daily, Lisinopril 10mg daily. "
            "Last HbA1c: 7.8% (2024-09-15). Goals: Reduce HbA1c below 7%."
        ),
        "lab_results": json.dumps([
            {
                "loinc": "2345-7", "name": "Glucose", "value": 210, "unit": "mg/dL",
                "reference_range": "70-100", "flag": "H", "status": "high"
            },
            {
                "loinc": "4548-4", "name": "HbA1c", "value": 8.2, "unit": "%",
                "reference_range": "4.0-5.6", "flag": "H", "status": "high"
            },
            {
                "loinc": "2160-0", "name": "Creatinine", "value": 1.1, "unit": "mg/dL",
                "reference_range": "0.7-1.3", "flag": None, "status": "normal"
            },
        ]),
        "expected_keys": ["summary", "key_findings", "dietary_suggestions",
                          "discuss_with_doctor", "context_used"],
        "must_mention": ["glucose", "hba1c", "metformin"],
        "must_discuss_with_doctor": True,  # has critical/high findings
    },
    {
        "id": "iron_deficiency_anaemia",
        "patient_context": (
            "Patient: 28-year-old female. Conditions: Iron deficiency anaemia (diagnosed 2024-01). "
            "Medications: Ferrous sulfate 325mg daily. Vegetarian diet. "
            "Goals: Improve energy levels, increase haemoglobin."
        ),
        "lab_results": json.dumps([
            {
                "loinc": "718-7", "name": "Hemoglobin", "value": 10.2, "unit": "g/dL",
                "reference_range": "12.0-16.0", "flag": "L", "status": "low"
            },
            {
                "loinc": "2498-4", "name": "Serum Iron", "value": 45, "unit": "ug/dL",
                "reference_range": "60-170", "flag": "L", "status": "low"
            },
            {
                "loinc": "2276-4", "name": "Ferritin", "value": 8, "unit": "ng/mL",
                "reference_range": "12-150", "flag": "L", "status": "low"
            },
        ]),
        "expected_keys": ["summary", "key_findings", "dietary_suggestions",
                          "discuss_with_doctor", "context_used"],
        "must_mention": ["hemoglobin", "iron", "ferritin"],
        "must_discuss_with_doctor": False,
    },
    {
        "id": "normal_panel_healthy",
        "patient_context": (
            "Patient: 35-year-old male. No known conditions. No medications. "
            "Active lifestyle, balanced diet. Annual check-up."
        ),
        "lab_results": json.dumps([
            {
                "loinc": "718-7", "name": "Hemoglobin", "value": 15.1, "unit": "g/dL",
                "reference_range": "13.5-17.5", "flag": None, "status": "normal"
            },
            {
                "loinc": "2345-7", "name": "Glucose", "value": 88, "unit": "mg/dL",
                "reference_range": "70-100", "flag": None, "status": "normal"
            },
            {
                "loinc": "2093-3", "name": "Total Cholesterol", "value": 185, "unit": "mg/dL",
                "reference_range": "<200", "flag": None, "status": "normal"
            },
        ]),
        "expected_keys": ["summary", "key_findings", "dietary_suggestions",
                          "discuss_with_doctor", "context_used"],
        "must_mention": ["hemoglobin", "glucose", "cholesterol"],
        "must_discuss_with_doctor": False,
    },
]


# ---------------------------------------------------------------------------
# Synthetic RAG retrieval test cases
# Each case: question + ground_truth_contexts (what the retriever SHOULD find)
# ---------------------------------------------------------------------------

RAG_CASES = [
    {
        "id": "statin_coq10",
        "question": "My doctor prescribed a statin. Should I take CoQ10?",
        "ground_truth_contexts": [
            "Statins inhibit HMG-CoA reductase and can reduce endogenous CoQ10 synthesis. "
            "Some guidelines recommend CoQ10 supplementation (100-200mg/day) for patients "
            "on statin therapy, particularly those experiencing myopathy symptoms.",
            "Drug-nutrient interaction: Statins (e.g. atorvastatin, rosuvastatin) deplete "
            "Coenzyme Q10. Supplementation may reduce statin-induced muscle pain."
        ],
        "reference_answer": (
            "Statins can reduce CoQ10 levels in your body. Some patients on statins "
            "benefit from CoQ10 supplementation, especially if experiencing muscle pain. "
            "Discuss with your doctor before starting any supplement."
        ),
    },
    {
        "id": "high_creatinine_meaning",
        "question": "What does a high creatinine level mean?",
        "ground_truth_contexts": [
            "Creatinine is a waste product filtered by the kidneys. Elevated serum creatinine "
            "(>1.3 mg/dL in men, >1.1 mg/dL in women) can indicate reduced kidney function. "
            "Causes include dehydration, acute kidney injury, or chronic kidney disease.",
            "eGFR (estimated glomerular filtration rate) is calculated from creatinine, age, "
            "and sex. An eGFR below 60 mL/min/1.73m² for 3+ months indicates CKD."
        ],
        "reference_answer": (
            "High creatinine suggests your kidneys may not be filtering waste efficiently. "
            "It can result from dehydration, kidney disease, or certain medications. "
            "Your doctor will likely want to monitor this or run further tests."
        ),
    },
    {
        "id": "low_vitamin_d",
        "question": "My vitamin D is 18 ng/mL. What should I do?",
        "ground_truth_contexts": [
            "Vitamin D deficiency is defined as serum 25-OH vitamin D below 20 ng/mL. "
            "Insufficiency: 20-29 ng/mL. Optimal: 30-100 ng/mL. "
            "Treatment: 1000-4000 IU vitamin D3 daily for deficiency.",
            "Vitamin D supports calcium absorption, bone health, and immune function. "
            "Deficiency is associated with increased fracture risk, fatigue, and depression."
        ],
        "reference_answer": (
            "A vitamin D level of 18 ng/mL is considered deficient (below 20 ng/mL). "
            "Supplementation with vitamin D3 and increased sun exposure can help. "
            "Your doctor may recommend a specific dose based on your overall health."
        ),
    },
]


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def interpret_cases():
    return INTERPRET_CASES


@pytest.fixture(scope="session")
def rag_cases():
    return RAG_CASES


@pytest.fixture(scope="session")
def openai_model():
    """Model to use for DeepEval judging."""
    from config import settings
    return settings.PRIMARY_MODEL
