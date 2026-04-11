"""
Offline MIPROv2 optimization harness.

Usage:
    python -m dspy_programs.optimize --program interpret  [--auto light|medium|heavy]
    python -m dspy_programs.optimize --program chat_context

What it does:
1. Configures DSPy with the primary (stronger) model for the teacher
   and fast model for the compiled student.
2. Loads a synthetic training set of health examples.
3. Runs MIPROv2 to find optimal instructions + few-shot demonstrations.
4. Saves the compiled program to dspy_compiled/{name}.json.

Compiled programs are loaded automatically at service startup via loader.py.
You should rerun this when:
  - You change a Signature definition
  - You add new training examples
  - Interpretation quality degrades over time

The training set here is synthetic but clinically realistic.
For production, replace/augment with real anonymised examples.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ─── Training data ─────────────────────────────────────────────────────────────

_INTERPRET_TRAINSET = [
    {
        "patient_context": (
            "Age: 52 years. Sex: M. Height: 178 cm. Weight: 90 kg. Activity: sedentary.\n"
            "Conditions: Type 2 diabetes (diagnosed 2019), hypertension.\n"
            "Medications: Metformin 1000 mg twice daily, Lisinopril 10 mg daily.\n"
            "Recent labs (90d): HbA1c 7.8% (high, 6 months ago), Creatinine 1.2 mg/dL (normal).\n"
            "Health goals: improve blood sugar control, lose weight."
        ),
        "lab_results": (
            "- HbA1c (LOINC 4548-4): 8.2% [ref: 4.0-5.6%] flag=H status=high\n"
            "- Fasting Glucose (LOINC 2345-7): 162 mg/dL [ref: 70-99] flag=H status=high\n"
            "- Creatinine (LOINC 2160-0): 1.3 mg/dL [ref: 0.7-1.2] flag=H status=high\n"
            "- eGFR (LOINC 62238-1): 58 mL/min/1.73m² [ref: >60] flag=L status=low\n"
            "- Total Cholesterol (LOINC 2093-3): 210 mg/dL [ref: <200] flag=H status=high\n"
            "- LDL (LOINC 13457-7): 135 mg/dL [ref: <100] flag=H status=high"
        ),
        "interpretation": json.dumps({
            "summary": "Your blood sugar control has worsened since your last test — HbA1c is now 8.2%, up from 7.8% six months ago. Your kidney function also shows early concern (eGFR 58) that warrants monitoring alongside your Metformin use. Cholesterol is elevated and needs attention.",
            "key_findings": [
                {"loinc": "4548-4", "name": "HbA1c", "value": "8.2%", "status": "high", "explanation": "Your average blood sugar over the past 3 months has worsened from 7.8% to 8.2%. For someone with Type 2 diabetes on Metformin, a target below 7% is generally recommended.", "trend": "worsening", "previous_value": "7.8%", "previous_date": "2023-12-15"},
                {"loinc": "62238-1", "name": "eGFR", "value": "58 mL/min/1.73m²", "status": "low", "explanation": "Your kidney filtration rate has dropped into Stage 3a CKD territory. This is important because Metformin requires dose adjustment at eGFR <45, and your trend warrants close monitoring.", "trend": "first_reading", "previous_value": None, "previous_date": None},
            ],
            "dietary_suggestions": [
                {"category": "decrease", "suggestion": "Refined carbohydrates and added sugars", "mechanism": "Your HbA1c of 8.2% indicates chronically elevated blood sugar — reducing simple carbs directly lowers post-meal glucose spikes.", "foods": ["white bread", "sugary drinks", "pastries", "white rice"], "priority": "high"},
            ],
            "lifestyle_suggestions": [
                {"category": "exercise", "suggestion": "30 minutes of brisk walking 5 days per week", "mechanism": "Regular moderate exercise improves insulin sensitivity, directly addressing your elevated HbA1c of 8.2% and supporting weight loss.", "priority": "high"},
            ],
            "drug_nutrient_flags": [
                {"medication": "Metformin", "depletes": "Vitamin B12", "interaction": "Metformin reduces B12 absorption in the gut over time", "suggestion": "Ask your doctor to check B12 levels at your next visit", "severity": "moderate"},
            ],
            "discuss_with_doctor": [
                {"finding": "eGFR 58 with rising creatinine on Metformin", "reason": "Metformin is contraindicated at eGFR <30 and requires monitoring below 45; your trend and diabetes combination warrants a kidney function review.", "urgency": "soon"},
                {"finding": "HbA1c worsening from 7.8% to 8.2%", "reason": "Glycaemic control has deteriorated despite current Metformin dose; medication adjustment or addition may be warranted.", "urgency": "soon"},
            ],
            "context_used": {"conditions_count": 2, "medications_count": 2, "recent_results_count": 1, "health_facts_count": 0},
        }),
    },
    {
        "patient_context": (
            "Age: 34 years. Sex: F. Height: 165 cm. Weight: 62 kg. Activity: moderately active.\n"
            "Conditions: Hypothyroidism (Hashimoto's).\n"
            "Medications: Levothyroxine 75 mcg daily.\n"
            "Recent labs (90d): TSH 3.2 mIU/L (normal, 4 months ago).\n"
            "Health goals: increase energy, manage thyroid health."
        ),
        "lab_results": (
            "- TSH (LOINC 3016-3): 4.8 mIU/L [ref: 0.4-4.0] flag=H status=high\n"
            "- Free T4 (LOINC 3026-2): 0.8 ng/dL [ref: 0.8-1.8] flag=none status=normal\n"
            "- Ferritin (LOINC 2276-4): 12 ng/mL [ref: 12-150] flag=none status=normal\n"
            "- Vitamin D (LOINC 1989-3): 18 ng/mL [ref: 30-100] flag=L status=low\n"
            "- Hemoglobin (LOINC 718-7): 11.8 g/dL [ref: 12.0-16.0] flag=L status=low"
        ),
        "interpretation": json.dumps({
            "summary": "Your TSH has risen to 4.8 — above the reference range and up from 3.2 four months ago — suggesting your thyroid dose may need adjustment. Your low Vitamin D (18 ng/mL) and borderline-low hemoglobin may be contributing to the fatigue you've been experiencing.",
            "key_findings": [
                {"loinc": "3016-3", "name": "TSH", "value": "4.8 mIU/L", "status": "high", "explanation": "Your TSH has risen from 3.2 (normal) four months ago to 4.8 (above range), suggesting your Hashimoto's is becoming less well-controlled on your current 75 mcg Levothyroxine dose.", "trend": "worsening", "previous_value": "3.2 mIU/L", "previous_date": "2023-11-01"},
                {"loinc": "1989-3", "name": "Vitamin D", "value": "18 ng/mL", "status": "low", "explanation": "At 18 ng/mL you are Vitamin D deficient. Low Vitamin D is associated with fatigue and may worsen autoimmune thyroid conditions like Hashimoto's.", "trend": "first_reading", "previous_value": None, "previous_date": None},
            ],
            "dietary_suggestions": [
                {"category": "increase", "suggestion": "Vitamin D-rich foods and supplementation", "mechanism": "Your Vitamin D of 18 ng/mL is well below the target of 40-60 ng/mL; supplementation is typically needed alongside dietary sources.", "foods": ["fatty fish", "egg yolks", "fortified milk", "mushrooms"], "priority": "high"},
            ],
            "lifestyle_suggestions": [
                {"category": "other", "suggestion": "Take Levothyroxine consistently 30-60 minutes before food on an empty stomach", "mechanism": "Inconsistent timing significantly affects absorption and explains TSH fluctuations in Hashimoto's patients.", "priority": "high"},
            ],
            "drug_nutrient_flags": [],
            "discuss_with_doctor": [
                {"finding": "TSH 4.8, up from 3.2 on Levothyroxine 75 mcg", "reason": "Rising TSH suggests underdosing; Levothyroxine dose adjustment is likely needed.", "urgency": "soon"},
            ],
            "context_used": {"conditions_count": 1, "medications_count": 1, "recent_results_count": 1, "health_facts_count": 0},
        }),
    },
    {
        "patient_context": (
            "Age: 45 years. Sex: F. Height: 170 cm. Weight: 75 kg. Activity: lightly active.\n"
            "Conditions: none.\n"
            "Medications: none.\n"
            "Recent labs (90d): none.\n"
            "Health goals: preventive health monitoring."
        ),
        "lab_results": (
            "- Total Cholesterol (LOINC 2093-3): 185 mg/dL [ref: <200] flag=none status=normal\n"
            "- LDL (LOINC 13457-7): 95 mg/dL [ref: <100] flag=none status=normal\n"
            "- HDL (LOINC 2085-9): 72 mg/dL [ref: >60 women] flag=none status=normal\n"
            "- Triglycerides (LOINC 2571-8): 88 mg/dL [ref: <150] flag=none status=normal\n"
            "- Fasting Glucose (LOINC 2345-7): 91 mg/dL [ref: 70-99] flag=none status=normal\n"
            "- TSH (LOINC 3016-3): 2.1 mIU/L [ref: 0.4-4.0] flag=none status=normal"
        ),
        "interpretation": json.dumps({
            "summary": "All your results are within normal ranges — this is an excellent preventive health baseline. Your HDL of 72 mg/dL is particularly good cardiovascular protection. No immediate concerns to flag.",
            "key_findings": [
                {"loinc": "2085-9", "name": "HDL Cholesterol", "value": "72 mg/dL", "status": "normal", "explanation": "Your HDL (the 'good' cholesterol) at 72 mg/dL is excellent — above 60 mg/dL is considered protective against heart disease.", "trend": "first_reading", "previous_value": None, "previous_date": None},
            ],
            "dietary_suggestions": [],
            "lifestyle_suggestions": [
                {"category": "exercise", "suggestion": "Maintain current activity level to preserve excellent HDL", "mechanism": "Regular aerobic exercise is the most effective lifestyle factor for raising HDL cholesterol.", "priority": "low"},
            ],
            "drug_nutrient_flags": [],
            "discuss_with_doctor": [],
            "context_used": {"conditions_count": 0, "medications_count": 0, "recent_results_count": 0, "health_facts_count": 0},
        }),
    },
]

_CHAT_CONTEXT_TRAINSET = [
    {
        "memories": (
            "- HbA1c was 7.8% in December 2023 (high)\n"
            "- Patient has Type 2 diabetes diagnosed 2019\n"
            "- Takes Metformin 1000 mg twice daily\n"
            "- Patient prefers simple, practical advice\n"
            "- Mentioned fatigue as main symptom in last session\n"
            "- Dislikes eating fish"
        ),
        "question": "My doctor just told me my HbA1c went up to 8.2%. What does that mean and what should I eat?",
        "focused_context": "Your HbA1c has risen from 7.8% (December 2023) to 8.2%, meaning your average blood sugar has worsened despite Metformin. You have Type 2 diabetes and prefer practical, simple advice — and you dislike fish, so seafood-based suggestions won't be relevant.",
    },
    {
        "memories": (
            "- Patient has Hashimoto's thyroidism\n"
            "- Takes Levothyroxine 75 mcg daily\n"
            "- TSH was 3.2 mIU/L four months ago (normal)\n"
            "- Patient mentioned taking Levothyroxine with coffee in the morning\n"
            "- Vitamin D was 22 ng/mL six months ago (low)"
        ),
        "question": "Why is my TSH going up even though I'm taking my thyroid medication?",
        "focused_context": "Your TSH rose from 3.2 to 4.8 mIU/L despite Levothyroxine 75 mcg. You mentioned taking it with coffee — this significantly reduces absorption (coffee can cut Levothyroxine bioavailability by up to 35%). Your previous Vitamin D deficiency (22 ng/mL) may also be contributing to Hashimoto's activity.",
    },
    {
        "memories": (
            "- No diagnosed conditions\n"
            "- No current medications\n"
            "- Exercises 3x per week\n"
            "- Interested in preventive health\n"
            "- Asked about cholesterol in a previous session"
        ),
        "question": "Can you explain what my cholesterol numbers mean?",
        "focused_context": "You have no diagnosed conditions or medications, exercise regularly, and have previously asked about cholesterol. You're focused on preventive health, so an explanation framed around long-term cardiovascular risk and lifestyle maintenance will be most relevant.",
    },
]


# ─── Metric functions ────────────────────────────────────────────────────────

def _interpret_metric(example: dspy.Example, prediction: dspy.Prediction, trace=None) -> float:
    """
    Score an interpretation output.
    Returns a float in [0, 1]:
      0.4  — valid JSON
      0.2  — has required top-level keys
      0.2  — key_findings is non-empty and each item has required subkeys
      0.2  — discuss_with_doctor present when high/critical findings exist
    """
    import dspy
    text = getattr(prediction, "interpretation", "") or ""
    score = 0.0

    # 1. Valid JSON
    try:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(json_match.group()) if json_match else json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return 0.0
    score += 0.4

    # 2. Required top-level keys
    required_keys = {"summary", "key_findings", "dietary_suggestions", "discuss_with_doctor"}
    if required_keys.issubset(data.keys()):
        score += 0.2

    # 3. key_findings items have required subkeys
    findings = data.get("key_findings", [])
    if findings:
        finding_keys = {"loinc", "name", "value", "status", "explanation"}
        if all(finding_keys.issubset(f.keys()) for f in findings):
            score += 0.2

    # 4. discuss_with_doctor populated for high/critical findings
    high_findings = [f for f in findings if f.get("status") in ("high", "critical", "low")]
    if high_findings:
        if data.get("discuss_with_doctor"):
            score += 0.2
    else:
        score += 0.2  # nothing to flag — full marks

    return score


def _chat_context_metric(example: dspy.Example, prediction: dspy.Prediction, trace=None) -> float:
    """
    Score a chat context refinement.
    Returns a float in [0, 1]:
      0.4  — output is non-empty and ≤ 5 sentences
      0.3  — contains at least one specific value/date from the memories
      0.3  — does not simply repeat all memories verbatim (some selection happened)
    """
    text = getattr(prediction, "focused_context", "") or ""
    if not text.strip():
        return 0.0

    score = 0.0
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]

    # 1. Non-empty and concise
    if 1 <= len(sentences) <= 5:
        score += 0.4

    # 2. Contains a specific detail (number, date, medication name)
    has_specific = bool(re.search(r"\d+(\.\d+)?|mg|mcg|ng/mL|%|mIU", text, re.IGNORECASE))
    if has_specific:
        score += 0.3

    # 3. Shorter than the raw memories (selection occurred)
    memories = getattr(example, "memories", "")
    if len(text) < len(memories) * 0.8:
        score += 0.3

    return score


# ─── Main ─────────────────────────────────────────────────────────────────────

def _make_dspy_examples(raw: list[dict], input_keys: list[str], output_key: str):
    import dspy
    return [
        dspy.Example(**{k: item[k] for k in input_keys + [output_key]}).with_inputs(*input_keys)
        for item in raw
    ]


def optimize_interpret(auto: str = "light"):
    import dspy
    from dspy.teleprompt import MIPROv2
    from config import settings
    from dspy_programs.programs import LabInterpretProgram

    teacher = dspy.LM(f"openai/{settings.PRIMARY_MODEL}", api_key=settings.OPENAI_API_KEY, cache=False)
    student = dspy.LM(f"openai/{settings.FAST_MODEL}", api_key=settings.OPENAI_API_KEY, cache=False)
    dspy.configure(lm=student)

    trainset = _make_dspy_examples(_INTERPRET_TRAINSET, ["patient_context", "lab_results"], "interpretation")
    program = LabInterpretProgram()

    optimizer = MIPROv2(
        metric=_interpret_metric,
        prompt_model=teacher,
        task_model=student,
        auto=auto,
        verbose=True,
    )

    compiled = optimizer.compile(program, trainset=trainset, requires_permission_to_run=False)

    out_path = Path(__file__).parent.parent / "dspy_compiled" / "interpret.json"
    out_path.parent.mkdir(exist_ok=True)
    compiled.save(str(out_path))
    print(f"Saved compiled interpret program → {out_path}")
    return compiled


def optimize_chat_context(auto: str = "light"):
    import dspy
    from dspy.teleprompt import MIPROv2
    from config import settings
    from dspy_programs.programs import ChatContextProgram

    teacher = dspy.LM(f"openai/{settings.PRIMARY_MODEL}", api_key=settings.OPENAI_API_KEY, cache=False)
    student = dspy.LM(f"openai/{settings.FAST_MODEL}", api_key=settings.OPENAI_API_KEY, cache=False)
    dspy.configure(lm=student)

    trainset = _make_dspy_examples(_CHAT_CONTEXT_TRAINSET, ["memories", "question"], "focused_context")
    program = ChatContextProgram()

    optimizer = MIPROv2(
        metric=_chat_context_metric,
        prompt_model=teacher,
        task_model=student,
        auto=auto,
        verbose=True,
    )

    compiled = optimizer.compile(program, trainset=trainset, requires_permission_to_run=False)

    out_path = Path(__file__).parent.parent / "dspy_compiled" / "chat_context.json"
    out_path.parent.mkdir(exist_ok=True)
    compiled.save(str(out_path))
    print(f"Saved compiled chat context program → {out_path}")
    return compiled


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MIPROv2 optimization")
    parser.add_argument("--program", choices=["interpret", "chat_context", "all"], default="all")
    parser.add_argument("--auto", choices=["light", "medium", "heavy"], default="light")
    args = parser.parse_args()

    if args.program in ("interpret", "all"):
        optimize_interpret(auto=args.auto)
    if args.program in ("chat_context", "all"):
        optimize_chat_context(auto=args.auto)
