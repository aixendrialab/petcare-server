-- schema.sql (orgs removed, user_roles has no org_id)

DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS pets CASCADE;
DROP TABLE IF EXISTS pet_reports CASCADE;
DROP TABLE IF EXISTS vaccinations CASCADE;
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

-- sample ancillary tables (optional in MVP)
CREATE TABLE IF NOT EXISTS pet_reports (
  id      SERIAL PRIMARY KEY,
  pet_id  INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  title   TEXT,
  uri     TEXT
);

CREATE TABLE IF NOT EXISTS vaccinations (
  id       SERIAL PRIMARY KEY,
  pet_id   INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  name     TEXT,
  given_on DATE
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

-- === PetCare App — Unified Schema (appointments, slots, invoices, vaccines) ===
-- Generated: 2025-09-24 04:04
-- This script DROPs and CREATES all tables relevant to Vet Appointments feature.
-- It intentionally avoids ALTERs as requested.

BEGIN;

-- Drop in reverse dependency order (safe for re-run in dev)
DROP TABLE IF EXISTS invoice_items CASCADE;
DROP TABLE IF EXISTS invoices CASCADE;
DROP TABLE IF EXISTS prescription_items CASCADE;
DROP TABLE IF EXISTS prescriptions CASCADE;
DROP TABLE IF EXISTS pet_vaccinations_given CASCADE;
DROP TABLE IF EXISTS pet_vaccination_plan CASCADE;
DROP TABLE IF EXISTS clinic_vaccine_enabled CASCADE;
DROP TABLE IF EXISTS vaccine_catalog CASCADE;
DROP TABLE IF EXISTS appointment_audit CASCADE;
DROP TABLE IF EXISTS appointments CASCADE;
DROP TABLE IF EXISTS slots CASCADE;
DROP TABLE IF EXISTS vet_schedule_templates CASCADE;

-- Existing base tables from your schema (referenced):
-- users(id, phone, email, name, active_role)
-- user_roles(id, user_id, role)
-- pets(id, owner_id, name, species, dob, gender, notes)
-- vet_profiles(user_id, legal_name, display_name, business_email, billing_email, billing_address, gstin, pan,
--              qualifications, license_no, experience_years, specialties, visit_in_clinic, visit_video, fee_in_clinic, fee_video, slot_minutes)
-- vet_locations(id, user_id, name, line1, line2, city, lat, lng, hours, is_primary)

-- 1) Scheduling templates (per vet/location/mode) — governs materialization of slots
CREATE TABLE vet_schedule_templates (
  id              SERIAL PRIMARY KEY,
  vet_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  location_id     INTEGER NOT NULL REFERENCES vet_locations(id) ON DELETE CASCADE,
  mode            TEXT NOT NULL CHECK (mode IN ('in_person','video')),
  slot_minutes    INTEGER NOT NULL DEFAULT 15 CHECK (slot_minutes > 0 AND slot_minutes <= 120),
  min_gap_minutes INTEGER NOT NULL DEFAULT 0 CHECK (min_gap_minutes >= 0 AND min_gap_minutes <= 60),
  workdays        INTEGER[] NOT NULL DEFAULT '{1,2,3,4,5,6}',  -- 1=Mon ... 7=Sun (Postgres convention: EXTRACT(ISODOW))
  day_start       TIME NOT NULL DEFAULT '09:00',
  day_end         TIME NOT NULL DEFAULT '18:00',
  breaks          JSONB NOT NULL DEFAULT '[]',   -- [{"start":"13:00","end":"14:00","label":"lunch"}]
  horizon_days    INTEGER NOT NULL DEFAULT 30,
  UNIQUE(vet_id, location_id, mode)
);

-- 2) Slots — materialized availability
CREATE TABLE slots (
  id           SERIAL PRIMARY KEY,
  vet_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  location_id  INTEGER NOT NULL REFERENCES vet_locations(id) ON DELETE CASCADE,
  mode         TEXT NOT NULL CHECK (mode IN ('in_person','video')),
  start_ts     TIMESTAMPTZ NOT NULL,
  end_ts       TIMESTAMPTZ NOT NULL,
  status       TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','HOLD','BOOKED')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT slots_time_ok CHECK (end_ts > start_ts)
);

CREATE INDEX ix_slots_lookup ON slots(vet_id, location_id, mode, start_ts);
CREATE INDEX ix_slots_status ON slots(status);

-- 3) Appointments — the core booking + visit state
CREATE TABLE appointments (
  id             SERIAL PRIMARY KEY,
  slot_id        INTEGER REFERENCES slots(id) ON DELETE SET NULL,
  vet_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  location_id    INTEGER NOT NULL REFERENCES vet_locations(id) ON DELETE CASCADE,
  parent_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  pet_id         INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  mode           TEXT NOT NULL CHECK (mode IN ('in_person','video')),
  start_ts       TIMESTAMPTZ NOT NULL,
  end_ts         TIMESTAMPTZ NOT NULL,
  calendar_state TEXT NOT NULL CHECK (calendar_state IN (
                   'CONFIRMED','RESCHEDULE_PROPOSED_BY_VET','RESCHEDULE_REQUESTED_BY_PARENT',
                   'CANCELLED_BY_PARENT','CANCELLED_BY_VET')),
  visit_state    TEXT CHECK (visit_state IN ('ARRIVED','IN_CONSULTATION','CONSULTATION_COMPLETE')),
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_appts_by_vet_date ON appointments(vet_id, start_ts);
CREATE INDEX ix_appts_by_parent ON appointments(parent_id, start_ts);
CREATE INDEX ix_appts_visit_state ON appointments(visit_state);

-- 4) Audit trail
CREATE TABLE appointment_audit (
  id             SERIAL PRIMARY KEY,
  appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_kind     TEXT NOT NULL CHECK (actor_kind IN ('parent','vet','system')),
  actor_id       INTEGER,
  action         TEXT NOT NULL,
  details_json   JSONB NOT NULL DEFAULT '{}'
);

-- 5) Clinical notes / prescriptions
CREATE TABLE prescriptions (
  id             SERIAL PRIMARY KEY,
  appointment_id INTEGER UNIQUE NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  diagnosis      TEXT,
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE prescription_items (
  id               SERIAL PRIMARY KEY,
  prescription_id  INTEGER NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
  drug_name        TEXT NOT NULL,
  dose             TEXT,          -- e.g., "1 tablet"
  frequency        TEXT,          -- e.g., "BID", "TID"
  before_after_food TEXT          -- e.g., "after food"
);

-- 6) Vaccines
CREATE TABLE vaccine_catalog (
  id            SERIAL PRIMARY KEY,
  species       TEXT NOT NULL CHECK (species IN ('dog','cat')),
  code          TEXT NOT NULL,
  name          TEXT NOT NULL,
  brand         TEXT,
  default_schedule_json JSONB NOT NULL DEFAULT '{}', -- e.g., {"initial_weeks":12,"booster_weeks":[16,52],"annual_every_weeks":52}
  UNIQUE(species, code)
);

CREATE TABLE clinic_vaccine_enabled (
  id         SERIAL PRIMARY KEY,
  vet_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  vaccine_id INTEGER NOT NULL REFERENCES vaccine_catalog(id) ON DELETE CASCADE,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  stock      INTEGER NOT NULL DEFAULT 0,
  UNIQUE(vet_id, vaccine_id)
);

CREATE TABLE pet_vaccination_plan (
  id          SERIAL PRIMARY KEY,
  pet_id      INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  vaccine_id  INTEGER NOT NULL REFERENCES vaccine_catalog(id) ON DELETE CASCADE,
  due_date    DATE NOT NULL,
  status      TEXT NOT NULL DEFAULT 'DUE' CHECK (status IN ('DUE','DONE','SKIPPED')),
  appointment_id INTEGER
);

CREATE TABLE pet_vaccinations_given (
  id           SERIAL PRIMARY KEY,
  pet_id       INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  vaccine_id   INTEGER NOT NULL REFERENCES vaccine_catalog(id) ON DELETE CASCADE,
  given_on     DATE NOT NULL,
  batch        TEXT,
  next_due     DATE,
  appointment_id INTEGER
);

-- 7) Invoices (GST-friendly)
CREATE TABLE invoices (
  id              SERIAL PRIMARY KEY,
  appointment_id  INTEGER UNIQUE NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
  vet_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  location_id     INTEGER NOT NULL REFERENCES vet_locations(id) ON DELETE CASCADE,
  invoice_no      TEXT NOT NULL,
  invoice_date    TIMESTAMPTZ NOT NULL DEFAULT now(),
  bill_to_parent_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  clinic_legal_name  TEXT NOT NULL,
  clinic_address     TEXT NOT NULL,
  gstin              TEXT,
  subtotal        NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_cgst        NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_sgst        NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_igst        NUMERIC(12,2) NOT NULL DEFAULT 0,
  total           NUMERIC(12,2) NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid','paid','void'))
);

CREATE UNIQUE INDEX ix_invoices_no ON invoices(invoice_no);

CREATE TABLE invoice_items (
  id          SERIAL PRIMARY KEY,
  invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  qty         NUMERIC(10,2) NOT NULL DEFAULT 1,
  unit_price  NUMERIC(12,2) NOT NULL DEFAULT 0,
  amount      NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_rate    NUMERIC(5,2) NOT NULL DEFAULT 0   -- e.g., 18.00 for 18%
);

COMMIT;