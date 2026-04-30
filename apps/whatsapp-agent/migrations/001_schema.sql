-- ════════════════════════════════════════════════════════════════════════════
-- Migration 001: Core schema for WhatsApp biomarker bot
-- ════════════════════════════════════════════════════════════════════════════
-- Apply with:  psql "$SUPABASE_DB_URL" -f 001_schema.sql
-- Idempotent — safe to re-run.
-- ════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── USERS ──────────────────────────────────────────────────────────────────
-- Identity = SHA-256(phone + pepper). Raw phone is encrypted in phone_encrypted.
CREATE TABLE IF NOT EXISTS users (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_hash               text UNIQUE NOT NULL,
  phone_encrypted          bytea,                       -- AES-GCM ciphertext (nonce || ct || tag)
  consent_given_at         timestamptz,
  consent_version          text,
  age_confirmed            boolean DEFAULT false,
  preferred_language       text DEFAULT 'en',
  conversation_summary     text,                        -- rolling summary, updated when convo > N turns
  total_messages           int DEFAULT 0,
  total_reports            int DEFAULT 0,
  daily_message_count      int DEFAULT 0,
  daily_pdf_count          int DEFAULT 0,
  daily_count_reset_on     date DEFAULT current_date,
  daily_spend_usd          numeric(10,4) DEFAULT 0,
  total_spend_usd          numeric(12,4) DEFAULT 0,
  blocked                  boolean DEFAULT false,
  blocked_reason           text,
  created_at               timestamptz DEFAULT now(),
  updated_at               timestamptz DEFAULT now(),
  deleted_at               timestamptz                  -- soft delete for DSAR
);
CREATE INDEX IF NOT EXISTS idx_users_phone_hash ON users(phone_hash);

-- ── LAB REPORTS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lab_reports (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  storage_path             text NOT NULL,               -- supabase://lab-reports/<key>
  source_msg_sid           text,                        -- Twilio MessageSid
  status                   text NOT NULL DEFAULT 'queued',  -- queued|processing|done|failed
  uploaded_at              timestamptz DEFAULT now(),
  processed_at             timestamptz,
  ocr_provider             text,                        -- mistral|gpt4o-vision
  ocr_raw_markdown         text,
  failure_reason           text,
  page_count               int,
  byte_size                int
);
CREATE INDEX IF NOT EXISTS idx_lab_reports_user ON lab_reports(user_id, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_lab_reports_status ON lab_reports(status) WHERE status IN ('queued','processing');

-- ── BIOMARKER RESULTS ──────────────────────────────────────────────────────
-- Each row = one test result. KG-ready via loinc_code.
CREATE TABLE IF NOT EXISTS biomarker_results (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  report_id                uuid NOT NULL REFERENCES lab_reports(id) ON DELETE CASCADE,
  loinc_code               text,                        -- nullable when unmapped
  test_name_raw            text NOT NULL,               -- as printed in the report
  test_name_normalized     text,                        -- our canonical name
  category                 text,                        -- lipids|liver|kidney|...
  tier                     int,                         -- 1=full, 2=soft, 3=defer
  value                    numeric,
  value_text               text,                        -- "positive"/"detected" non-numeric
  unit                     text,
  ref_range_text           text,
  ref_range_low            numeric,
  ref_range_high           numeric,
  status                   text,                        -- llm-classified: high|low|normal|critical|inconclusive
  measured_at              date,
  created_at               timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bio_results_user_loinc ON biomarker_results(user_id, loinc_code, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_bio_results_report ON biomarker_results(report_id);

-- ── REPORT-LEVEL EXPLANATIONS ──────────────────────────────────────────────
-- Stores the natural-language explanation we gave for each biomarker, so
-- next time we can recall: "remember when I told you LDL is the bad cholesterol?"
CREATE TABLE IF NOT EXISTS report_biomarker_explanations (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  report_id                uuid NOT NULL REFERENCES lab_reports(id) ON DELETE CASCADE,
  loinc_code               text,
  explanation_text         text NOT NULL,
  created_at               timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_explanations_user_loinc ON report_biomarker_explanations(user_id, loinc_code, created_at DESC);

-- ── CONVERSATIONS ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role                     text NOT NULL,               -- user|assistant|system
  content                  text NOT NULL,
  msg_type                 text DEFAULT 'text',         -- text|pdf|image|report_reply|emergency
  twilio_sid               text,                        -- Twilio MessageSid (inbound or outbound)
  extracted_entities       jsonb,                       -- {biomarkers:[...], symptoms:[...], conditions:[...]}
  prompt_version           text,
  model_used               text,
  tokens_in                int,
  tokens_out               int,
  cost_usd                 numeric(10,6),
  created_at               timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user_time ON conversations(user_id, created_at DESC);

-- ── USER FACTS (KG-seed) ───────────────────────────────────────────────────
-- Structured durable facts extracted from conversations.
CREATE TABLE IF NOT EXISTS user_facts (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fact_type                text NOT NULL,               -- symptom|condition|medication|lifestyle|preference|demographic
  fact_key                 text NOT NULL,               -- e.g. "fatigue", "diabetes_type_2", "vegetarian"
  fact_value               text NOT NULL,               -- "yes"|"intermittent"|"since 2026-03"
  source_conversation_id   uuid REFERENCES conversations(id) ON DELETE SET NULL,
  confidence               numeric(3,2) DEFAULT 0.8,    -- 0.00–1.00
  learned_at               timestamptz DEFAULT now(),
  superseded_at            timestamptz                  -- when contradicted/updated
);
CREATE INDEX IF NOT EXISTS idx_user_facts_active ON user_facts(user_id, fact_type) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_user_facts_key ON user_facts(user_id, fact_key) WHERE superseded_at IS NULL;

-- ── MESSAGE QUEUE (table-based, simple, durable) ───────────────────────────
-- Worker polls this table with FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS message_queue (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                  uuid REFERENCES users(id) ON DELETE CASCADE,
  payload                  jsonb NOT NULL,              -- {type:"pdf"|"text", body, twilio_sid, media_url, ...}
  status                   text NOT NULL DEFAULT 'pending',  -- pending|processing|done|failed
  attempts                 int DEFAULT 0,
  max_attempts             int DEFAULT 3,
  created_at               timestamptz DEFAULT now(),
  processing_started_at    timestamptz,
  processed_at             timestamptz,
  error                    text,
  visible_after            timestamptz DEFAULT now()    -- for delayed retries
);
CREATE INDEX IF NOT EXISTS idx_queue_pending ON message_queue(visible_after, created_at)
  WHERE status = 'pending';

-- ── IDEMPOTENCY (don't double-process Twilio webhooks) ─────────────────────
CREATE TABLE IF NOT EXISTS processed_messages (
  twilio_sid               text PRIMARY KEY,
  processed_at             timestamptz DEFAULT now()
);
-- Auto-cleanup older than 7 days via pg_cron (configured separately)

-- ── RATE LIMIT EVENTS (sliding window) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limit_events (
  id                       bigserial PRIMARY KEY,
  user_id                  uuid REFERENCES users(id) ON DELETE CASCADE,
  event_type               text NOT NULL,               -- 'message' | 'pdf'
  occurred_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ratelimit_user_type_time
  ON rate_limit_events(user_id, event_type, occurred_at DESC);

-- ── AUDIT LOG (append-only) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
  id                       bigserial PRIMARY KEY,
  user_id                  uuid REFERENCES users(id) ON DELETE SET NULL,
  action                   text NOT NULL,
  metadata                 jsonb,
  ip_hash                  text,
  created_at               timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ── TRIGGERS ───────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_touch ON users;
CREATE TRIGGER users_touch BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Reset daily counters lazily (called from app code on each request)
CREATE OR REPLACE FUNCTION reset_daily_counters_if_needed(uid uuid) RETURNS void AS $$
BEGIN
  UPDATE users
     SET daily_message_count = 0,
         daily_pdf_count     = 0,
         daily_spend_usd     = 0,
         daily_count_reset_on = current_date
   WHERE id = uid AND daily_count_reset_on < current_date;
END $$ LANGUAGE plpgsql;
