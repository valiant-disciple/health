-- Migration 002: Universal health events ledger
-- Every health data point routes through this table.
-- New modalities add rows, never new columns.

CREATE TABLE IF NOT EXISTS health_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  event_type      TEXT NOT NULL,
  -- 'lab_result' | 'wearable_reading' | 'cgm_reading' | 'meal' |
  -- 'workout' | 'symptom' | 'vital' | 'mood' | 'sleep_session' |
  -- 'medication_dose' | 'supplement' | 'body_measurement'

  -- Bi-temporal
  occurred_at     TIMESTAMPTZ NOT NULL,
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Source provenance
  source          TEXT NOT NULL,
  source_device   TEXT,

  -- Universal biomarker abstraction (LOINC)
  biomarker_code  TEXT,
  biomarker_name  TEXT,
  value_numeric   FLOAT,
  value_text      TEXT,
  unit            TEXT,
  reference_low   FLOAT,
  reference_high  FLOAT,
  personal_target FLOAT,
  status          TEXT CHECK (status IN ('normal','watch','discuss','low','high','critical')),
  confidence      TEXT DEFAULT 'confirmed' CHECK (confidence IN ('confirmed','estimated','inferred')),

  -- Pointer to detail table
  detail_table    TEXT,
  detail_id       UUID,

  -- Temporal validity
  valid_from      TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until     TIMESTAMPTZ,

  -- Vector DB pointer
  embedding_id    TEXT,

  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_he_user_occurred ON health_events(user_id, occurred_at DESC);
CREATE INDEX idx_he_user_type     ON health_events(user_id, event_type);
CREATE INDEX idx_he_biomarker     ON health_events(user_id, biomarker_code, occurred_at DESC);
CREATE INDEX idx_he_status        ON health_events(user_id, status) WHERE status != 'normal';
CREATE INDEX idx_he_valid         ON health_events(user_id, valid_from, valid_until);

ALTER TABLE health_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own events"
  ON health_events USING (user_id = auth.uid());
