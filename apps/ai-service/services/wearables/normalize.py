"""
Normalize wearable readings into the canonical health_events row shape.
All providers funnel through here before Supabase insert + Qdrant upsert.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

# Apple Health ↔ LOINC mapping for the types we ingest
APPLE_TYPE_MAP: dict[str, dict] = {
    "HKQuantityTypeIdentifierHeartRate":           {"loinc": "8867-4",  "name": "Heart Rate",          "unit": "bpm",   "event_type": "heart_rate"},
    "HKQuantityTypeIdentifierRestingHeartRate":    {"loinc": "40443-4", "name": "Resting Heart Rate",   "unit": "bpm",   "event_type": "heart_rate"},
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": {"loinc": "80404-7", "name": "HRV (SDNN)",    "unit": "ms",    "event_type": "hrv"},
    "HKQuantityTypeIdentifierOxygenSaturation":   {"loinc": "2708-6",  "name": "SpO2",                 "unit": "%",     "event_type": "spo2"},
    "HKQuantityTypeIdentifierStepCount":          {"loinc": "55423-8", "name": "Steps",                "unit": "steps", "event_type": "activity"},
    "HKQuantityTypeIdentifierActiveEnergyBurned": {"loinc": "41981-2", "name": "Active Energy",        "unit": "kcal",  "event_type": "activity"},
    "HKQuantityTypeIdentifierBasalEnergyBurned":  {"loinc": "41979-6", "name": "Basal Energy",         "unit": "kcal",  "event_type": "activity"},
    "HKQuantityTypeIdentifierDistanceWalkingRunning": {"loinc": "55430-3", "name": "Distance",        "unit": "km",    "event_type": "activity"},
    "HKQuantityTypeIdentifierBodyMass":           {"loinc": "29463-7", "name": "Body Weight",          "unit": "kg",    "event_type": "body_measurement"},
    "HKQuantityTypeIdentifierBodyMassIndex":      {"loinc": "39156-5", "name": "BMI",                  "unit": "kg/m2", "event_type": "body_measurement"},
    "HKQuantityTypeIdentifierBodyFatPercentage":  {"loinc": "41982-0", "name": "Body Fat %",           "unit": "%",     "event_type": "body_measurement"},
    "HKQuantityTypeIdentifierBloodPressureSystolic":  {"loinc": "8480-6",  "name": "Systolic BP",    "unit": "mmHg",  "event_type": "blood_pressure"},
    "HKQuantityTypeIdentifierBloodPressureDiastolic": {"loinc": "8462-4",  "name": "Diastolic BP",   "unit": "mmHg",  "event_type": "blood_pressure"},
    "HKQuantityTypeIdentifierBloodGlucose":       {"loinc": "2339-0",  "name": "Blood Glucose",       "unit": "mg/dL", "event_type": "lab_result"},
    "HKCategoryTypeIdentifierSleepAnalysis":      {"loinc": "93832-4", "name": "Sleep",               "unit": "hours", "event_type": "sleep"},
}

# Fitbit API field → LOINC mapping
FITBIT_TYPE_MAP: dict[str, dict] = {
    "heart_rate":       {"loinc": "8867-4",  "name": "Heart Rate",        "unit": "bpm",   "event_type": "heart_rate"},
    "resting_hr":       {"loinc": "40443-4", "name": "Resting Heart Rate", "unit": "bpm",   "event_type": "heart_rate"},
    "hrv_rmssd":        {"loinc": "80404-7", "name": "HRV (RMSSD)",        "unit": "ms",    "event_type": "hrv"},
    "spo2":             {"loinc": "2708-6",  "name": "SpO2",               "unit": "%",     "event_type": "spo2"},
    "steps":            {"loinc": "55423-8", "name": "Steps",              "unit": "steps", "event_type": "activity"},
    "calories_active":  {"loinc": "41981-2", "name": "Active Calories",    "unit": "kcal",  "event_type": "activity"},
    "distance_km":      {"loinc": "55430-3", "name": "Distance",           "unit": "km",    "event_type": "activity"},
    "weight_kg":        {"loinc": "29463-7", "name": "Body Weight",        "unit": "kg",    "event_type": "body_measurement"},
    "bmi":              {"loinc": "39156-5", "name": "BMI",                "unit": "kg/m2", "event_type": "body_measurement"},
    "fat_pct":          {"loinc": "41982-0", "name": "Body Fat %",         "unit": "%",     "event_type": "body_measurement"},
    "minutes_asleep":   {"loinc": "93832-4", "name": "Sleep Duration",     "unit": "hours", "event_type": "sleep"},
}


def to_health_event(
    user_id: str,
    mapping: dict,
    value: float,
    occurred_at: str,
    source: str,
    source_device: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Build a health_events insert dict from a normalized reading."""
    return {
        "user_id":        user_id,
        "event_type":     mapping["event_type"],
        "occurred_at":    occurred_at,
        "recorded_at":    datetime.now(timezone.utc).isoformat(),
        "source":         source,
        "source_device":  source_device,
        "biomarker_code": mapping["loinc"],
        "biomarker_name": mapping["name"],
        "value_numeric":  round(float(value), 4),
        "unit":           mapping["unit"],
        "status":         "normal",           # wearables don't carry ref ranges
        "metadata":       metadata or {},
    }
