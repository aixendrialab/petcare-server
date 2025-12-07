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
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename  = 'slot_settings'
      AND indexname  = 'ix_slot_settings_ctx'
  ) THEN
    CREATE INDEX ix_slot_settings_ctx
      ON public.slot_settings (user_id, location_id, consultation_type);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename  = 'slot_settings'
      AND indexname  = 'ix_slot_settings_ctx_range'
  ) THEN
    CREATE INDEX ix_slot_settings_ctx_range
      ON public.slot_settings (user_id, location_id, consultation_type, effective_from, effective_to);
  END IF;
END $$;

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

-- 1) Create enum type
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'appointment_state') THEN
        CREATE TYPE appointment_state AS ENUM (
            'BOOKED',
            'CANCELLED_BY_PARENT',
            'CANCELLED_BY_VET',
            'COMPLETED',
            'NO_SHOW',
            'ARRIVED',
            'IN_CONSULT'
        );
    END IF;
END$$;

CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,

    slot_id TExt NOT NULL, 

    vet_id INTEGER NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    location_id INTEGER NOT NULL
        REFERENCES vet_locations(id)
        ON DELETE CASCADE,

    parent_id INTEGER NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    pet_id INTEGER NOT NULL
        REFERENCES pets(id)
        ON DELETE CASCADE,

    mode TEXT NOT NULL,                      -- "in_person" | "video"
    
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts   TIMESTAMPTZ NOT NULL,

    calendar_state TEXT NOT NULL,            -- "booked", "rescheduled", "cancelled", etc.
    visit_state TEXT,                        -- "ARRIVED", "IN_CONSULTATION", etc.

    notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE appointments ADD CONSTRAINT uq_appointment_unique UNIQUE (location_id, start_ts, end_ts);


-- 2) Cast column to enum (assuming it is currently TEXT/VARCHAR)
ALTER TABLE appointments
    ALTER COLUMN calendar_state TYPE appointment_state
    USING calendar_state::appointment_state;

-- One active booking per clinic / start time
CREATE UNIQUE INDEX IF NOT EXISTS ux_appt_booked_location_start
ON appointments (location_id, start_ts)
WHERE calendar_state = 'BOOKED';

-- One active booking per parent / start time (no double-book across vets)
CREATE UNIQUE INDEX IF NOT EXISTS ux_appt_booked_parent_start
ON appointments (parent_id, start_ts)
WHERE calendar_state = 'BOOKED';

-- 1) main consult table
CREATE TABLE IF NOT EXISTS consult (
    id              SERIAL PRIMARY KEY,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id),
    pet_id          INTEGER NOT NULL REFERENCES pets(id),
    vet_id          INTEGER NOT NULL REFERENCES vet_profiles(user_id),
    reason          TEXT,
    findings        TEXT,
    diagnosis       TEXT,
    advice          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 2) vitals
CREATE TABLE IF NOT EXISTS consult_vitals (
    id          SERIAL PRIMARY KEY,
    consult_id  INTEGER NOT NULL REFERENCES consult(id) ON DELETE CASCADE,
    weight_kg   NUMERIC(5,2),
    temp_c      NUMERIC(4,1),
    heart_rate  INTEGER,
    resp_rate   INTEGER,
    notes       TEXT
);

-- 3) medications
CREATE TABLE IF NOT EXISTS consult_medication (
    id          SERIAL PRIMARY KEY,
    consult_id  INTEGER NOT NULL REFERENCES consult(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    dose        VARCHAR(255),
    frequency   VARCHAR(255),
    days        INTEGER,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS ix_consult_pet ON consult(pet_id);
CREATE INDEX IF NOT EXISTS ix_consult_vet ON consult(vet_id, created_at DESC);

CREATE TABLE vaccination_record (
    id SERIAL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    vaccine_name TEXT NOT NULL,          -- e.g., "Rabies", "DHPPi", "Parvo", "Kennel Cough"
    vaccine_type TEXT,                   -- core / non-core / optional
    last_given DATE,                     -- last administered date
    next_due DATE,                       -- next booster or scheduled
    status TEXT CHECK (status IN ('DUE', 'UPCOMING', 'COMPLETED', 'MISSED')) DEFAULT 'UPCOMING',
    batch_no TEXT,                       -- vaccine batch # (optional)
    manufacturer TEXT,                   -- optional manufacturer info
    notes TEXT,                          -- vet notes
    vet_id INTEGER REFERENCES vet_profiles(user_id), -- who administered
    location_id INTEGER REFERENCES vet_locations(id),

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

ALTER TABLE pets
  ADD COLUMN microchip TEXT,
  ADD COLUMN blood_group TEXT,
  ADD COLUMN is_neutered BOOLEAN DEFAULT FALSE,
  ADD COLUMN allergies TEXT,
  ADD COLUMN chronic_conditions TEXT,
  ADD COLUMN behavior_notes TEXT,
  ADD COLUMN weight_kg NUMERIC,
  ADD COLUMN color_markings TEXT;

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_appt_vet_state_start
    ON appointments(vet_id, calendar_state, start_ts);

CREATE INDEX IF NOT EXISTS ix_appt_parent_state_start
    ON appointments(parent_id, calendar_state, start_ts);