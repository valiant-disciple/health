-- Migration 006: Food, symptoms, body measurements, mood

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
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meal_id       UUID NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
  food_name     TEXT NOT NULL,
  usda_fdc_id   TEXT,
  quantity_g    FLOAT,
  calories      FLOAT,
  protein_g     FLOAT,
  carbs_g       FLOAT,
  fat_g         FLOAT,
  fiber_g       FLOAT,
  nutrients     JSONB
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
