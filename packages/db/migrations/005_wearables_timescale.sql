-- Migration 005: Wearable readings (TimescaleDB hypertable)
-- Run AFTER enabling TimescaleDB extension in Supabase:
--   Dashboard → Database → Extensions → Enable timescaledb

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS wearable_readings (
  time        TIMESTAMPTZ NOT NULL,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  device      TEXT NOT NULL,
  metric      TEXT NOT NULL,
  value       FLOAT NOT NULL,
  unit        TEXT,
  confidence  FLOAT DEFAULT 1.0,
  source_raw  JSONB
);

SELECT create_hypertable('wearable_readings', 'time', if_not_exists => TRUE);

CREATE INDEX idx_wr_user_metric ON wearable_readings(user_id, metric, time DESC);
CREATE INDEX idx_wr_device      ON wearable_readings(user_id, device, time DESC);

-- Enable compression for data older than 7 days
ALTER TABLE wearable_readings SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'user_id,device,metric'
);
SELECT add_compression_policy('wearable_readings', INTERVAL '7 days');

-- Continuous aggregate: 5-minute averages
CREATE MATERIALIZED VIEW wearable_5min
WITH (timescaledb.continuous) AS
  SELECT
    time_bucket('5 minutes', time) AS bucket,
    user_id, device, metric,
    AVG(value)   AS avg_val,
    MIN(value)   AS min_val,
    MAX(value)   AS max_val,
    COUNT(*)     AS sample_count
  FROM wearable_readings
  GROUP BY bucket, user_id, device, metric
WITH NO DATA;

SELECT add_continuous_aggregate_policy('wearable_5min',
  start_offset      => INTERVAL '1 day',
  end_offset        => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour'
);

-- NOTE: RLS on TimescaleDB hypertables uses the parent table policy
ALTER TABLE wearable_readings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own wearable data"
  ON wearable_readings USING (user_id = auth.uid());
