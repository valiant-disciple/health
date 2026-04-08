-- Migration 001: User profile and health conditions
-- Run this in Supabase SQL editor after creating your project

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

CREATE INDEX idx_conditions_user  ON health_conditions(user_id);
CREATE INDEX idx_conditions_valid ON health_conditions(user_id, valid_from, valid_until);

ALTER TABLE health_conditions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own conditions"
  ON health_conditions USING (user_id = auth.uid());

-- Auto-update updated_at on user_profile
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_profile_updated_at
  BEFORE UPDATE ON user_profile
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
