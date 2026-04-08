-- Migration 007: Conversations, messages, health facts (memory layer)

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

CREATE INDEX idx_conv_user ON conversations(user_id, created_at DESC);

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

CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own messages"
  ON messages USING (user_id = auth.uid());


CREATE TABLE IF NOT EXISTS health_facts (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  fact_type        TEXT NOT NULL,
  -- 'lab_pattern' | 'food_response' | 'lifestyle_insight' |
  -- 'symptom_pattern' | 'medication_effect' | 'goal_preference' | 'clinical_flag'
  content          TEXT NOT NULL,
  confidence       FLOAT DEFAULT 0.8,
  supporting_events UUID[],
  graphiti_id      TEXT,
  valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_until      TIMESTAMPTZ,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_facts_user_type ON health_facts(user_id, fact_type);
CREATE INDEX idx_facts_valid     ON health_facts(user_id, valid_from, valid_until);

ALTER TABLE health_facts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own facts"
  ON health_facts USING (user_id = auth.uid());


-- Audit log for HIPAA access tracking
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

CREATE INDEX idx_audit_user ON audit_log(user_id, created_at DESC);
-- Audit log is append-only: no RLS update/delete policies
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read own audit log"
  ON audit_log FOR SELECT USING (user_id = auth.uid());
