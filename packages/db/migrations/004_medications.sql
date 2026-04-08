-- Migration 004: Medications with staleness tracking

CREATE TABLE IF NOT EXISTS medications (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name                 TEXT NOT NULL,
  rxnorm_code          TEXT,
  ndc_code             TEXT,
  generic_name         TEXT,
  brand_name           TEXT,
  dose_amount          FLOAT,
  dose_unit            TEXT,
  frequency            TEXT,
  route                TEXT,
  timing               TEXT,
  indication           TEXT,
  prescribing_provider TEXT,
  started_date         DATE NOT NULL,
  stopped_date         DATE,
  status               TEXT DEFAULT 'active'
    CHECK (status IN ('active','paused','stopped','as_needed','unknown')),
  -- If not confirmed in 90 days → prompt user to verify still taking
  last_confirmed_at    TIMESTAMPTZ DEFAULT now(),
  source               TEXT DEFAULT 'self_reported'
    CHECK (source IN ('self_reported','prescription_upload','ehr_import')),
  notes                TEXT,
  valid_from           TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until          TIMESTAMPTZ,
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_meds_user_active ON medications(user_id, status) WHERE status = 'active';
CREATE INDEX idx_meds_staleness   ON medications(user_id, last_confirmed_at) WHERE status = 'active';

ALTER TABLE medications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own medications"
  ON medications USING (user_id = auth.uid());

CREATE TRIGGER update_medications_updated_at
  BEFORE UPDATE ON medications
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
