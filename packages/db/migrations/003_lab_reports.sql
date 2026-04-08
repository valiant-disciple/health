-- Migration 003: Lab reports and results

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

CREATE INDEX idx_lr_user_date ON lab_reports(user_id, created_at DESC);
CREATE INDEX idx_lr_status    ON lab_reports(user_id, processing_status);

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

CREATE INDEX idx_results_report ON lab_results(report_id);
CREATE INDEX idx_results_user   ON lab_results(user_id, loinc_code, occurred_at DESC);

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
