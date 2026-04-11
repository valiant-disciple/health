-- ============================================================
-- health — Combined Migration
-- Paste this entire file into: Supabase → SQL Editor → New query → Run
-- ============================================================

-- ─── 001: User profile ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_profile (
  id                   UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name         TEXT,
  date_of_birth        DATE,
  sex                  TEXT CHECK (sex IN ('male','female','other','prefer_not_to_say')),
  height_cm            FLOAT,
  weight_kg            FLOAT,
  activity_level       TEXT CHECK (activity_level IN ('sedentary','light','moderate','active','very_active')),
  health_goals         TEXT[],
  dietary_restrictions TEXT[],
  food_preferences     JSONB DEFAULT '{}',
  onboarding_complete  BOOLEAN DEFAULT false,
  timezone             TEXT DEFAULT 'UTC',
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE user_profile ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own profile"
  ON user_profile USING (id = auth.uid());

CREATE TABLE IF NOT EXISTS health_conditions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  icd10_code    TEXT,
  snomed_code   TEXT,
  severity      TEXT CHECK (severity IN ('mild','moderate','severe','in_remission')),
  diagnosed_at  DATE,
  resolved_at   DATE,
  source        TEXT DEFAULT 'self_reported',
  notes         TEXT,
  valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conditions_user  ON health_conditions(user_id);
CREATE INDEX IF NOT EXISTS idx_conditions_valid ON health_conditions(user_id, valid_from, valid_until);

ALTER TABLE health_conditions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own conditions"
  ON health_conditions USING (user_id = auth.uid());

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_profile_updated_at
  BEFORE UPDATE ON user_profile
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ─── 002: Universal health events ledger ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS health_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  event_type      TEXT NOT NULL,
  occurred_at     TIMESTAMPTZ NOT NULL,
  recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  source          TEXT NOT NULL,
  source_device   TEXT,
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
  detail_table    TEXT,
  detail_id       UUID,
  valid_from      TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until     TIMESTAMPTZ,
  embedding_id    TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_he_user_occurred ON health_events(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_he_user_type     ON health_events(user_id, event_type);
CREATE INDEX IF NOT EXISTS idx_he_biomarker     ON health_events(user_id, biomarker_code, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_he_status        ON health_events(user_id, status) WHERE status != 'normal';
CREATE INDEX IF NOT EXISTS idx_he_valid         ON health_events(user_id, valid_from, valid_until);

ALTER TABLE health_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own events"
  ON health_events USING (user_id = auth.uid());

-- ─── 003: Lab reports ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS lab_reports (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  file_path         TEXT NOT NULL,
  file_name         TEXT,
  report_date       DATE,
  lab_name          TEXT,
  ordering_provider TEXT,
  ocr_raw           TEXT,
  processing_status TEXT DEFAULT 'pending'
    CHECK (processing_status IN ('pending','processing','completed','failed')),
  processed_at      TIMESTAMPTZ,
  spike_report_id   TEXT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lr_user_date ON lab_reports(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_lr_status    ON lab_reports(user_id, processing_status);

ALTER TABLE lab_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own reports"
  ON lab_reports USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS lab_results (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id       UUID NOT NULL REFERENCES lab_reports(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  health_event_id UUID REFERENCES health_events(id),
  loinc_code      TEXT NOT NULL,
  loinc_name      TEXT NOT NULL,
  display_name    TEXT,
  value_numeric   FLOAT,
  value_text      TEXT,
  unit            TEXT,
  ref_range_low   FLOAT,
  ref_range_high  FLOAT,
  ref_range_text  TEXT,
  status          TEXT CHECK (status IN ('normal','watch','discuss','low','high','critical')),
  flag            TEXT,
  occurred_at     TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_results_report ON lab_results(report_id);
CREATE INDEX IF NOT EXISTS idx_results_user   ON lab_results(user_id, loinc_code, occurred_at DESC);

ALTER TABLE lab_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own results"
  ON lab_results USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS report_interpretations (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id      UUID NOT NULL REFERENCES lab_reports(id) ON DELETE CASCADE,
  user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  interpretation JSONB NOT NULL,
  model_used     TEXT,
  langfuse_trace TEXT,
  faithfulness   FLOAT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE report_interpretations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own interpretations"
  ON report_interpretations USING (user_id = auth.uid());

-- ─── 004: Medications ─────────────────────────────────────────────────────────

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
  last_confirmed_at    TIMESTAMPTZ DEFAULT now(),
  source               TEXT DEFAULT 'self_reported'
    CHECK (source IN ('self_reported','prescription_upload','ehr_import')),
  notes                TEXT,
  valid_from           TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until          TIMESTAMPTZ,
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meds_user_active ON medications(user_id, status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_meds_staleness   ON medications(user_id, last_confirmed_at) WHERE status = 'active';

ALTER TABLE medications ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own medications"
  ON medications USING (user_id = auth.uid());

CREATE TRIGGER update_medications_updated_at
  BEFORE UPDATE ON medications
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ─── 005: Wearable readings (plain Postgres — TimescaleDB not available on Supabase free tier) ──

CREATE TABLE IF NOT EXISTS wearable_readings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  time        TIMESTAMPTZ NOT NULL,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  device      TEXT NOT NULL,
  metric      TEXT NOT NULL,
  value       FLOAT NOT NULL,
  unit        TEXT,
  confidence  FLOAT DEFAULT 1.0,
  source_raw  JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wr_user_metric ON wearable_readings(user_id, metric, time DESC);
CREATE INDEX IF NOT EXISTS idx_wr_device      ON wearable_readings(user_id, device, time DESC);
-- Partition-friendly: most queries filter by user + time range
CREATE INDEX IF NOT EXISTS idx_wr_user_time   ON wearable_readings(user_id, time DESC);

ALTER TABLE wearable_readings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own wearable data"
  ON wearable_readings USING (user_id = auth.uid());

-- ─── 006: Food, symptoms, body, mood ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meals (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  health_event_id  UUID REFERENCES health_events(id),
  meal_type        TEXT CHECK (meal_type IN ('breakfast','lunch','dinner','snack')),
  eaten_at         TIMESTAMPTZ NOT NULL,
  notes            TEXT,
  photo_path       TEXT,
  total_calories   FLOAT,
  total_protein    FLOAT,
  total_carbs      FLOAT,
  total_fat        FLOAT,
  glycemic_load    FLOAT,
  created_at       TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE meals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own meals" ON meals USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS meal_items (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meal_id     UUID NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  food_name   TEXT NOT NULL,
  usda_fdc_id TEXT,
  quantity_g  FLOAT,
  calories    FLOAT,
  protein_g   FLOAT,
  carbs_g     FLOAT,
  fat_g       FLOAT,
  fiber_g     FLOAT,
  nutrients   JSONB
);

CREATE TABLE IF NOT EXISTS symptoms (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  health_event_id  UUID REFERENCES health_events(id),
  snomed_code      TEXT,
  name             TEXT NOT NULL,
  severity         INTEGER CHECK (severity BETWEEN 1 AND 10),
  body_location    TEXT,
  duration_mins    INTEGER,
  occurred_at      TIMESTAMPTZ NOT NULL,
  notes            TEXT,
  possible_causes  TEXT[],
  created_at       TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE symptoms ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own symptoms" ON symptoms USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS body_measurements (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  health_event_id  UUID REFERENCES health_events(id),
  metric           TEXT NOT NULL,
  value            FLOAT NOT NULL,
  unit             TEXT,
  measured_at      TIMESTAMPTZ NOT NULL,
  source           TEXT DEFAULT 'manual',
  created_at       TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE body_measurements ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own measurements" ON body_measurements USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS mood_logs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  health_event_id  UUID REFERENCES health_events(id),
  score            INTEGER CHECK (score BETWEEN 1 AND 10),
  energy_level     INTEGER CHECK (energy_level BETWEEN 1 AND 10),
  stress_level     INTEGER CHECK (stress_level BETWEEN 1 AND 10),
  sleep_quality    INTEGER CHECK (sleep_quality BETWEEN 1 AND 10),
  notes            TEXT,
  logged_at        TIMESTAMPTZ NOT NULL,
  created_at       TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE mood_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own mood logs" ON mood_logs USING (user_id = auth.uid());

-- ─── 007: Conversations, messages, health facts, audit log ────────────────────

CREATE TABLE IF NOT EXISTS conversations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  context_type TEXT DEFAULT 'general'
    CHECK (context_type IN ('general','report_interpretation','trend_review')),
  context_id   UUID,
  title        TEXT,
  summary      TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at DESC);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own conversations"
  ON conversations USING (user_id = auth.uid());
CREATE TRIGGER update_conversations_updated_at
  BEFORE UPDATE ON conversations
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  content         TEXT NOT NULL,
  tool_calls      JSONB,
  citations       JSONB,
  langfuse_trace  TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own messages"
  ON messages USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS health_facts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  fact_type         TEXT NOT NULL,
  content           TEXT NOT NULL,
  confidence        FLOAT DEFAULT 0.8,
  supporting_events UUID[],
  graphiti_id       TEXT,
  valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until       TIMESTAMPTZ,
  created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_facts_user_type ON health_facts(user_id, fact_type);
CREATE INDEX IF NOT EXISTS idx_facts_valid     ON health_facts(user_id, valid_from, valid_until);
ALTER TABLE health_facts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own facts"
  ON health_facts USING (user_id = auth.uid());

CREATE TABLE IF NOT EXISTS audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID,
  actor_id    UUID,
  action      TEXT,
  resource    TEXT,
  resource_id UUID,
  ip_address  INET,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read own audit log"
  ON audit_log FOR SELECT USING (user_id = auth.uid());

-- ─── Storage bucket ───────────────────────────────────────────────────────────

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'lab-reports', 'lab-reports', false, 10485760,
  ARRAY['application/pdf','image/jpeg','image/png','image/heic','image/webp']
)
ON CONFLICT (id) DO NOTHING;

CREATE POLICY "Users can upload own lab reports"
  ON storage.objects FOR INSERT
  WITH CHECK (bucket_id = 'lab-reports' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can read own lab reports"
  ON storage.objects FOR SELECT
  USING (bucket_id = 'lab-reports' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Users can delete own lab reports"
  ON storage.objects FOR DELETE
  USING (bucket_id = 'lab-reports' AND auth.uid()::text = (storage.foldername(name))[1]);
