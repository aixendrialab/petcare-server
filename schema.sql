-- schema.sql (orgs removed, user_roles has no org_id)

DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS pets CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS vet_profiles CASCADE;
DROP TABLE IF EXISTS vet_locations CASCADE;

-- users: carries the current active_role (single “context”)
CREATE TABLE IF NOT EXISTS users (
  id          SERIAL PRIMARY KEY,
  phone       TEXT UNIQUE NOT NULL,
  email       TEXT UNIQUE,
  name        TEXT,
  active_role TEXT
    CHECK (active_role IS NULL OR active_role IN
      ('parent','vet','hostel','vendor','pharmacist','nutritionist','walker')),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone ON users(phone);

-- user_roles: which roles the user has (no org_id)
CREATE TABLE IF NOT EXISTS user_roles (
  id       SERIAL PRIMARY KEY,
  user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role     TEXT NOT NULL CHECK (role IN
            ('parent','vet','hostel','vendor','pharmacist','nutritionist','walker')),
  UNIQUE (user_id, role)
);

-- pets owned by a user
CREATE TABLE IF NOT EXISTS pets (
  id           SERIAL PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  breed        TEXT,
  dob          DATE,
  gender       TEXT,
  vaccine_status TEXT,
  rewards      TEXT,
  picture_uri  TEXT
);

CREATE TABLE vet_profiles (
  user_id           INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

  -- Business identity (for invoices, clinic comms)
  legal_name        TEXT,           -- e.g., "Paws Care LLP" (GST invoices)
  display_name      TEXT,           -- e.g., "Dr. Sangeeta" or "Paws Care – T Nagar"
  business_email    TEXT,           -- invoices/clinic email
  billing_email     TEXT,           -- optional, if different
  billing_address   TEXT,           -- free text for now (addr lines\ncity\npincode)
  gstin             TEXT,           -- India GST number (string, may start with digits/letters)
  pan               TEXT,           -- optional

  -- Professional details
  qualifications    TEXT,           -- "BVSc & AH, MVSc"
  license_no        TEXT,
  experience_years  INTEGER CHECK (experience_years >= 0),
  specialties       JSONB DEFAULT '[]',  -- ["dermatology","surgery"]

  -- Consult settings
  visit_in_clinic   BOOLEAN DEFAULT TRUE,
  visit_video       BOOLEAN DEFAULT TRUE,
  fee_in_clinic     INTEGER DEFAULT 0 CHECK (fee_in_clinic >= 0),
  fee_video         INTEGER DEFAULT 0 CHECK (fee_video >= 0),
  slot_minutes      INTEGER DEFAULT 15 CHECK (slot_minutes BETWEEN 5 AND 120),

  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE OR REPLACE FUNCTION trg_touch_vet_profiles() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS touch_vet_profiles ON vet_profiles;
CREATE TRIGGER touch_vet_profiles
  BEFORE UPDATE ON vet_profiles
  FOR EACH ROW EXECUTE FUNCTION trg_touch_vet_profiles();

CREATE TABLE vet_locations (
  id          SERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT,               -- "Paws Clinic (T Nagar)"
  line1       TEXT,
  line2       TEXT,
  city        TEXT,
  lat         DOUBLE PRECISION,
  lng         DOUBLE PRECISION,
  hours       TEXT,               -- e.g., "Mon–Sat 09:00–18:00"
  is_primary  BOOLEAN DEFAULT FALSE
);  

CREATE INDEX IF NOT EXISTS ix_vet_locations_user ON vet_locations(user_id);

CREATE TABLE IF NOT EXISTS slot_settings (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  location_id INT NULL REFERENCES vet_locations(id) ON DELETE CASCADE,
  consultation_type VARCHAR(16) NOT NULL,  -- 'in_person' | 'video'
  slot_minutes INT NOT NULL DEFAULT 15,
  gap_minutes INT NOT NULL DEFAULT 0,
  per_slot_capacity INT NOT NULL DEFAULT 1,
  lead_time_minutes INT NOT NULL DEFAULT 0,
  booking_window_days INT NOT NULL DEFAULT 30,
  visible_to_parents BOOLEAN NOT NULL DEFAULT TRUE,
  week_rules JSONB NOT NULL DEFAULT '{}',
  blackout_dates JSONB NOT NULL DEFAULT '[]',
  effective_from DATE NULL,
  effective_to DATE NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'uq_slot_settings_ctx'
  ) THEN
    CREATE UNIQUE INDEX uq_slot_settings_ctx
      ON slot_settings (user_id, location_id, consultation_type);
  END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_slot_settings_effective
  ON slot_settings (effective_from, effective_to);

CREATE TABLE IF NOT EXISTS slot_overrides (
  id SERIAL PRIMARY KEY,
  slot_setting_id INT NOT NULL REFERENCES slot_settings(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname = 'uq_slot_overrides_day'
  ) THEN
    CREATE UNIQUE INDEX uq_slot_overrides_day
      ON slot_overrides (slot_setting_id, date);
  END IF;
END$$;