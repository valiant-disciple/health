"""One-time generator: turn health-kg/data/biomarkers_enriched.json into our
runtime data file at data/supported_biomarkers.json.

Adds:
  - tier (1=full / 2=specialist deferral / 3=hard refuse)
  - aliases (common names + Indian lab terminology)
  - specialist (for tier 2 — e.g. urologist)

Usage:  python scripts/build_supported_biomarkers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path("/Users/kolosus/Documents/health-kg/data/biomarkers_enriched.json")
DEST = Path(__file__).resolve().parents[1] / "data" / "supported_biomarkers.json"


# ── Tier rules (category-based, with per-name overrides) ──────────────────
# Tier 1: routine, safe to interpret fully
# Tier 2: specialist context required (cancer markers, autoimmune, advanced cardiac)
# Tier 3: should not interpret at all (rarely shows up in routine panels)

TIER_BY_CATEGORY: dict[str, int] = {
    "cbc":              1,
    "hematology":       1,
    "lipid":            1,
    "hepatic":          1,
    "renal":            1,
    "thyroid":          1,
    "metabolic":        1,
    "vitamin":          1,
    "mineral":          1,
    "electrolyte":      1,
    "inflammation":     1,
    "cmp":              1,
    "urinalysis":       1,
    "muscle":           1,
    "bone":             1,
    "pancreatic":       1,
    "hormone":          2,    # endocrine — needs specialist
    "cardiac":          2,    # troponin, BNP — emergency context
    "cancer_marker":    2,    # tumor markers — oncologist
    "autoimmune":       2,    # ANA, RF — rheumatologist
    "infectious":       2,    # serology — infectious disease specialist
    "coagulation":      2,    # PT/INR — hematologist
    "immune":           1,
}

SPECIALIST_BY_CATEGORY: dict[str, str] = {
    "hormone":       "endocrinologist",
    "cardiac":       "cardiologist",
    "cancer_marker": "oncologist",
    "autoimmune":    "rheumatologist",
    "infectious":    "infectious disease specialist",
    "coagulation":   "hematologist",
}

# Per-biomarker overrides (LOINC code → tier)
TIER_OVERRIDES: dict[str, int] = {
    # examples — adjust as we learn what users actually upload
}

# Aliases supplement what's in the KG. Indian lab terminology especially.
ALIASES_BY_NAME: dict[str, list[str]] = {
    "WBC":               ["White Blood Cell Count", "Total Leucocyte Count", "TLC", "Leukocyte Count"],
    "RBC":               ["Red Blood Cell Count", "Erythrocyte Count"],
    "Hemoglobin":        ["Hb", "HGB", "Haemoglobin"],
    "Hematocrit":        ["HCT", "PCV", "Packed Cell Volume", "Haematocrit"],
    "MCV":               ["Mean Corpuscular Volume"],
    "MCH":               ["Mean Corpuscular Hemoglobin"],
    "MCHC":              ["Mean Corpuscular Hemoglobin Concentration"],
    "RDW":               ["Red Cell Distribution Width"],
    "Platelets":         ["Platelet Count", "PLT"],
    "MPV":               ["Mean Platelet Volume"],
    "Neutrophils":       ["Neutrophils %", "Neutrophil Count", "ANC"],
    "Lymphocytes":       ["Lymphocytes %", "Lymphocyte Count"],
    "Monocytes":         ["Monocytes %", "Monocyte Count"],
    "Eosinophils":       ["Eosinophils %", "Eosinophil Count"],
    "Basophils":         ["Basophils %", "Basophil Count"],
    "Glucose":           ["Fasting Blood Sugar", "FBS", "Blood Glucose Fasting", "Plasma Glucose"],
    "HbA1c":             ["Glycated Hemoglobin", "Glycosylated Hemoglobin", "A1c"],
    "Total Cholesterol": ["Cholesterol", "TC"],
    "LDL Cholesterol":   ["LDL", "LDL-C", "Low Density Lipoprotein", "LDL Direct"],
    "HDL Cholesterol":   ["HDL", "HDL-C", "High Density Lipoprotein"],
    "Triglycerides":     ["TG", "TGL"],
    "VLDL Cholesterol":  ["VLDL", "VLDL-C"],
    "ALT":               ["SGPT", "Alanine Aminotransferase", "ALT (SGPT)"],
    "AST":               ["SGOT", "Aspartate Aminotransferase", "AST (SGOT)"],
    "ALP":               ["Alkaline Phosphatase", "ALK PHOS"],
    "GGT":               ["Gamma GT", "Gamma-Glutamyl Transferase"],
    "Total Bilirubin":   ["Bilirubin Total", "T.Bil", "TBIL"],
    "Direct Bilirubin":  ["Bilirubin Direct", "D.Bil", "Conjugated Bilirubin"],
    "Indirect Bilirubin":["Bilirubin Indirect", "I.Bil", "Unconjugated Bilirubin"],
    "Albumin":           ["Serum Albumin"],
    "Total Protein":     ["Serum Total Protein", "Protein Total"],
    "Creatinine":        ["Serum Creatinine", "Creat"],
    "BUN":               ["Blood Urea Nitrogen", "Urea Nitrogen"],
    "Urea":              ["Blood Urea", "Serum Urea"],
    "Uric Acid":         ["Serum Uric Acid", "URIC"],
    "TSH":               ["Thyroid Stimulating Hormone", "Thyrotropin"],
    "FT3":               ["Free T3", "Free Triiodothyronine"],
    "FT4":               ["Free T4", "Free Thyroxine"],
    "T3":                ["Triiodothyronine", "Total T3"],
    "T4":                ["Thyroxine", "Total T4"],
    "Vitamin D":         ["25-OH Vitamin D", "25 Hydroxy Vitamin D", "Vit D", "Vitamin D Total", "25(OH)D"],
    "Vitamin B12":       ["B12", "Cobalamin", "Cyanocobalamin"],
    "Folate":            ["Folic Acid", "Vitamin B9", "Serum Folate"],
    "Ferritin":          ["Serum Ferritin"],
    "Iron":              ["Serum Iron", "Fe"],
    "TIBC":              ["Total Iron Binding Capacity"],
    "Calcium":           ["Serum Calcium", "Total Calcium", "Ca"],
    "Magnesium":         ["Serum Magnesium", "Mg"],
    "Phosphorus":        ["Serum Phosphorus", "Phosphate", "P"],
    "Sodium":            ["Serum Sodium", "Na"],
    "Potassium":         ["Serum Potassium", "K"],
    "Chloride":          ["Serum Chloride", "Cl"],
    "CRP":               ["C-Reactive Protein", "C Reactive Protein"],
    "hs-CRP":            ["High Sensitivity CRP", "Hs-CRP"],
    "ESR":               ["Erythrocyte Sedimentation Rate", "Sedimentation Rate"],
}

# Hard-blocked report types (document-level rejection, not per-biomarker)
HARD_BLOCKED_REPORT_KEYWORDS = [
    "histopathology", "biopsy report", "biopsy",
    "radiology report", "x-ray report", "ct scan", "mri scan", "ultrasound report",
    "echocardiogram", "echocardiography", "ecg report", "ekg report",
    "pap smear", "cytology report",
    "genetic test", "genetic screening", "nipt", "karyotype",
    "endoscopy", "colonoscopy",
]


def main() -> None:
    if not SRC.exists():
        print(f"FATAL: source not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    with SRC.open() as f:
        kg_biomarkers = json.load(f)

    out: list[dict] = []
    for b in kg_biomarkers:
        loinc = b.get("loinc")
        name = b.get("name")
        full = b.get("full_name") or name
        category = b.get("category", "unknown")

        tier = TIER_OVERRIDES.get(loinc, TIER_BY_CATEGORY.get(category, 2))
        specialist = SPECIALIST_BY_CATEGORY.get(category)

        aliases = ALIASES_BY_NAME.get(name, [])
        # Always include the full_name as an alias if different from name
        if full and full != name and full not in aliases:
            aliases = [full] + aliases

        out.append({
            "loinc": loinc,
            "name": name,
            "full_name": full,
            "aliases": aliases,
            "category": category,
            "organ_system": b.get("organ_system"),
            "tier": tier,
            "specialist": specialist,
            "common_units": [b.get("unit")] if b.get("unit") else [],
            "ref_range_general": b.get("ref_range_general"),
            "ref_range_male": b.get("ref_range_male"),
            "ref_range_female": b.get("ref_range_female"),
            "critical_low": b.get("critical_low"),
            "critical_high": b.get("critical_high"),
            "what_it_measures": b.get("what_it_measures"),
            "clinical_significance": b.get("clinical_significance"),
            "fasting_required": b.get("fasting_required", False),
        })

    DEST.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "biomarker_count": len(out),
        "biomarkers": out,
        "blocked_report_keywords": HARD_BLOCKED_REPORT_KEYWORDS,
    }
    with DEST.open("w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Summary
    by_tier = {1: 0, 2: 0, 3: 0}
    for b in out:
        by_tier[b["tier"]] = by_tier.get(b["tier"], 0) + 1
    print(f"✓ Wrote {DEST}")
    print(f"  {len(out)} biomarkers")
    print(f"  Tier 1 (full):       {by_tier[1]}")
    print(f"  Tier 2 (specialist): {by_tier[2]}")
    print(f"  Tier 3 (block):      {by_tier[3]}")


if __name__ == "__main__":
    main()
