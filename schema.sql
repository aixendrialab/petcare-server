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


ALTER TABLE pets ADD COLUMN IF NOT EXISTS species TEXT CHECK (species IN ('dog','cat'));

-- 1) Master catalog
CREATE TABLE IF NOT EXISTS vaccine_catalog (
  code        TEXT NOT NULL,  -- 'RABIES', 'DHPP', 'FVRCP', 'FELV'
  species     TEXT NOT NULL CHECK (species IN ('dog','cat')),
  name        TEXT NOT NULL,  -- display name
  vaccine_type TEXT NOT NULL DEFAULT 'core' CHECK (vaccine_type IN ('core','optional')),
  description TEXT,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,

  PRIMARY KEY (code, species)
);

-- Helpful index for browsing
CREATE INDEX IF NOT EXISTS ix_vaccine_catalog_species ON vaccine_catalog(species);


-- 2) Vaccination history/record (actual administered doses)
CREATE TABLE IF NOT EXISTS vaccination_record (
  id             SERIAL PRIMARY KEY,
  pet_id         INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,

  vaccine_code   TEXT NOT NULL,
  vaccine_species TEXT NOT NULL CHECK (vaccine_species IN ('dog','cat')),

  vaccine_type   TEXT,              -- core / optional (can store snapshot for history)
  last_given     DATE,
  next_due       DATE,

  batch_no       TEXT,
  manufacturer   TEXT,
  notes          TEXT,

  vet_id         INTEGER REFERENCES vet_profiles(user_id),
  location_id    INTEGER REFERENCES vet_locations(id),

  created_at     TIMESTAMP DEFAULT now(),
  updated_at     TIMESTAMP DEFAULT now(),

  CONSTRAINT fk_vacc_record_catalog
    FOREIGN KEY (vaccine_code, vaccine_species)
    REFERENCES vaccine_catalog(code, species)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_vacc_record_pet ON vaccination_record(pet_id);
CREATE INDEX IF NOT EXISTS ix_vacc_record_next_due ON vaccination_record(next_due);


-- 3) Default schedule “recipe” per species
CREATE TABLE IF NOT EXISTS vaccine_rule (
  id                    SERIAL PRIMARY KEY,

  species               TEXT NOT NULL CHECK (species IN ('dog','cat')),

  vaccine_code          TEXT NOT NULL,
  vaccine_species       TEXT NOT NULL CHECK (vaccine_species IN ('dog','cat')),

  -- schedule recipe (simple)
  start_age_weeks       INT NULL,
  dose_count            INT NOT NULL DEFAULT 1,
  dose_interval_days    INT NOT NULL DEFAULT 21,
  booster_interval_days INT NULL,

  is_active             BOOLEAN NOT NULL DEFAULT TRUE,

  CONSTRAINT ck_vaccine_rule_species_match
    CHECK (species = vaccine_species),

  CONSTRAINT fk_vaccine_rule_catalog
    FOREIGN KEY (vaccine_code, vaccine_species)
    REFERENCES vaccine_catalog(code, species)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_vaccine_rule_species ON vaccine_rule(species);
CREATE INDEX IF NOT EXISTS ix_vaccine_rule_vaccine ON vaccine_rule(vaccine_code, vaccine_species);


-- 4) One plan per pet (generated / confirmed)
CREATE TABLE IF NOT EXISTS pet_vaccine_plan (
  id SERIAL PRIMARY KEY,
  pet_id INT NOT NULL REFERENCES pets(id) ON DELETE CASCADE,

  status TEXT NOT NULL DEFAULT 'SUGGESTED'
    CHECK (status IN ('SUGGESTED','VET_CONFIRMED')),

  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ NULL,
  confirmed_by_vet_id INT NULL REFERENCES vet_profiles(user_id),

  notes TEXT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pet_vaccine_plan_pet ON pet_vaccine_plan(pet_id);


-- 5) Plan items (due schedule)
CREATE TABLE IF NOT EXISTS pet_vaccine_plan_item (
  id SERIAL PRIMARY KEY,
  plan_id INT NOT NULL REFERENCES pet_vaccine_plan(id) ON DELETE CASCADE,

  vaccine_code    TEXT NOT NULL,
  vaccine_species TEXT NOT NULL CHECK (vaccine_species IN ('dog','cat')),

  dose_no INT NOT NULL DEFAULT 1,
  due_on  DATE NOT NULL,

  status TEXT NOT NULL DEFAULT 'UPCOMING'
    CHECK (status IN ('DUE','UPCOMING','COMPLETED','MISSED','SKIPPED')),

  completed_on DATE NULL,
  completed_record_id INT NULL REFERENCES vaccination_record(id),

  overridden BOOLEAN NOT NULL DEFAULT FALSE,
  override_reason TEXT NULL,

  CONSTRAINT fk_plan_item_catalog
    FOREIGN KEY (vaccine_code, vaccine_species)
    REFERENCES vaccine_catalog(code, species)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_plan_item_due ON pet_vaccine_plan_item(due_on, status);
CREATE INDEX IF NOT EXISTS ix_plan_item_plan ON pet_vaccine_plan_item(plan_id);


-- 6) Appointment-level intent (parent requests vaccine action during consult)
CREATE TABLE IF NOT EXISTS vaccination_intent (
  id SERIAL PRIMARY KEY,
  appointment_id INT NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  pet_id INT NOT NULL REFERENCES pets(id) ON DELETE CASCADE,

  requested_vaccine_code TEXT NULL,
  requested_vaccine_species TEXT NULL CHECK (requested_vaccine_species IN ('dog','cat')),

  requested_action TEXT NOT NULL DEFAULT 'ADMINISTER'
    CHECK (requested_action IN ('ADMINISTER','CONFIRM_PLAN','BOTH')),

  parent_notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- if one is set, the other must be set
  CONSTRAINT ck_vacc_intent_vaccine_pair
    CHECK (
      (requested_vaccine_code IS NULL AND requested_vaccine_species IS NULL)
      OR
      (requested_vaccine_code IS NOT NULL AND requested_vaccine_species IS NOT NULL)
    ),

  CONSTRAINT fk_vacc_intent_catalog
    FOREIGN KEY (requested_vaccine_code, requested_vaccine_species)
    REFERENCES vaccine_catalog(code, species)
    ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vacc_intent_appt ON vaccination_intent(appointment_id);
CREATE INDEX IF NOT EXISTS ix_vacc_intent_pet ON vaccination_intent(pet_id);