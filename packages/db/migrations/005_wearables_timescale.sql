-- Migration 005: Wearable readings
-- Plain Postgres table — TimescaleDB not available on Supabase free tier.
-- Can migrate to a dedicated TimescaleDB instance later when wearable volume justifies it.

CREATE TABLE IF NOT EXISTS wearable_readings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  time        TIMESTAMPTZ NOT NULL,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  device      TEXT NOT NULL,   -- 'apple_watch' | 'garmin' | 'oura' | 'polar' | 'libre'
  metric      TEXT NOT NULL,   -- 'heart_rate' | 'hrv' | 'steps' | 'spo2' | 'skin_temp'
  value       FLOAT NOT NULL,
  unit        TEXT,
  confidence  FLOAT DEFAULT 1.0,
  source_raw  JSONB,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wr_user_metric ON wearable_readings(user_id, metric, time DESC);
CREATE INDEX IF NOT EXISTS idx_wr_device      ON wearable_readings(user_id, device, time DESC);
CREATE INDEX IF NOT EXISTS idx_wr_user_time   ON wearable_readings(user_id, time DESC);

ALTER TABLE wearable_readings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own wearable data"
  ON wearable_readings USING (user_id = auth.uid());
