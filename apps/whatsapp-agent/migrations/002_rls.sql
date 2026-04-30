-- ════════════════════════════════════════════════════════════════════════════
-- Migration 002: Row-Level Security
-- ════════════════════════════════════════════════════════════════════════════
-- The service_role key bypasses RLS by default — that's how our server-side
-- code reaches all rows. RLS here is a safety net: if anyone gets hold of
-- the anon key (or we accidentally expose tables), they cannot read other users'
-- data unless they're authenticated as that user.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE biomarker_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_biomarker_explanations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- service_role bypasses RLS, so server-side code is unaffected.
-- These policies only matter if anon/authenticated keys touch these tables
-- (which they shouldn't in this app — but defense in depth).

-- Users: a user can only see their own row
DROP POLICY IF EXISTS users_self_read ON users;
CREATE POLICY users_self_read ON users FOR SELECT
  USING (auth.uid() = id);

-- Lab reports: user owns their reports
DROP POLICY IF EXISTS lab_reports_owner ON lab_reports;
CREATE POLICY lab_reports_owner ON lab_reports FOR ALL
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS biomarker_results_owner ON biomarker_results;
CREATE POLICY biomarker_results_owner ON biomarker_results FOR ALL
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS explanations_owner ON report_biomarker_explanations;
CREATE POLICY explanations_owner ON report_biomarker_explanations FOR ALL
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS conversations_owner ON conversations;
CREATE POLICY conversations_owner ON conversations FOR ALL
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_facts_owner ON user_facts;
CREATE POLICY user_facts_owner ON user_facts FOR ALL
  USING (auth.uid() = user_id);

-- Internal tables: server-only — no policies grant access to anon/auth.
-- Leaving RLS enabled with no permissive policies = fully restricted.
