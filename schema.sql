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
  id          SERIAL PRIMARY KEY,

  code        TEXT NOT NULL,  -- 'RABIES', 'DHPP', 'FVRCP', 'FELV'
  species     TEXT NOT NULL CHECK (species IN ('dog','cat')),
  name        TEXT NOT NULL,
  vaccine_type TEXT NOT NULL DEFAULT 'core' CHECK (vaccine_type IN ('core','optional')),
  description TEXT,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- unique business key
CREATE UNIQUE INDEX IF NOT EXISTS uq_vaccine_catalog_code_species
  ON vaccine_catalog(code, species);

CREATE INDEX IF NOT EXISTS ix_vaccine_catalog_species
  ON vaccine_catalog(species);


-- 2) Vaccination history/record (actual administered doses)
CREATE TABLE IF NOT EXISTS vaccination_record (
  id             SERIAL PRIMARY KEY,
  pet_id         INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,

  vaccine_id     INT NOT NULL REFERENCES vaccine_catalog(id) ON DELETE RESTRICT,

  vaccine_type   TEXT,            -- optional snapshot
  last_given     DATE,
  next_due       DATE,

  batch_no       TEXT,
  manufacturer   TEXT,
  notes          TEXT,

  vet_id         INTEGER REFERENCES vet_profiles(user_id),
  location_id    INTEGER REFERENCES vet_locations(id),

  created_at     TIMESTAMP DEFAULT now(),
  updated_at     TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_vacc_record_pet ON vaccination_record(pet_id);
CREATE INDEX IF NOT EXISTS ix_vacc_record_next_due ON vaccination_record(next_due);


-- 3) Default schedule “recipe” per species
CREATE TABLE IF NOT EXISTS vaccine_rule (
  id                    SERIAL PRIMARY KEY,

  species               TEXT NOT NULL CHECK (species IN ('dog','cat')),

  vaccine_id            INT NOT NULL REFERENCES vaccine_catalog(id) ON DELETE CASCADE,

  start_age_weeks       INT NULL,
  dose_count            INT NOT NULL DEFAULT 1,
  dose_interval_days    INT NOT NULL DEFAULT 21,
  booster_interval_days INT NULL,

  is_active             BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS ix_vaccine_rule_species ON vaccine_rule(species);
CREATE INDEX IF NOT EXISTS ix_vaccine_rule_vaccine_id ON vaccine_rule(vaccine_id);


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

  vaccine_id INT NOT NULL REFERENCES vaccine_catalog(id) ON DELETE RESTRICT,

  dose_no INT NOT NULL DEFAULT 1,
  due_on  DATE NOT NULL,

  status TEXT NOT NULL DEFAULT 'UPCOMING'
    CHECK (status IN ('DUE','UPCOMING','COMPLETED','MISSED','SKIPPED')),

  completed_on DATE NULL,
  completed_record_id INT NULL REFERENCES vaccination_record(id),

  overridden BOOLEAN NOT NULL DEFAULT FALSE,
  override_reason TEXT NULL
);

CREATE INDEX IF NOT EXISTS ix_plan_item_due ON pet_vaccine_plan_item(due_on, status);
CREATE INDEX IF NOT EXISTS ix_plan_item_plan ON pet_vaccine_plan_item(plan_id);
CREATE INDEX IF NOT EXISTS ix_plan_item_vaccine ON pet_vaccine_plan_item(vaccine_id);


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
-- =========================================================
-- COMMERCE SCHEMA v2 (DROP + CREATE)
-- Goal: Amazon-like PDP + recos + variants + seller store page
-- =========================================================

-- ---------------------------------------------------------
-- Updated-at trigger helper (keep as-is)
-- ---------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END$$ LANGUAGE plpgsql;

-- =========================================================
-- 1) DELIVERY ADDRESSES
-- =========================================================
DROP TABLE IF EXISTS user_addresses CASCADE;

CREATE TABLE user_addresses (
  id           SERIAL PRIMARY KEY,
  user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  label        TEXT,              -- "Home", "Office"
  recipient    TEXT NOT NULL,
  phone        TEXT,

  line1        TEXT NOT NULL,
  line2        TEXT,
  landmark     TEXT,
  city         TEXT NOT NULL,
  state        TEXT NOT NULL,
  pincode      TEXT NOT NULL,

  lat          DOUBLE PRECISION,
  lng          DOUBLE PRECISION,

  is_default   BOOLEAN NOT NULL DEFAULT FALSE,

  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_user_addresses_user ON user_addresses(user_id);
CREATE UNIQUE INDEX ux_user_default_address ON user_addresses(user_id) WHERE is_default = TRUE;

DROP TRIGGER IF EXISTS touch_user_addresses ON user_addresses;
CREATE TRIGGER touch_user_addresses
BEFORE UPDATE ON user_addresses
FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();


-- =========================================================
-- 2) STORES (SELLERS)
-- =========================================================
DROP TABLE IF EXISTS store_badges CASCADE;
DROP TABLE IF EXISTS provider_stores CASCADE;

CREATE TABLE provider_stores (
  id            SERIAL PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  role          TEXT NOT NULL CHECK (role IN ('vendor','pharmacist','nutritionist','hostel')),
  display_name  TEXT NOT NULL,

  phone         TEXT,
  email         TEXT,

  logo_uri      TEXT,
  about         TEXT,

  status        TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE','PENDING','SUSPENDED')),

  address_line1 TEXT,
  address_line2 TEXT,
  city          TEXT,
  state         TEXT,
  pincode       TEXT,

  -- pharmacy specific
  license_no         TEXT,
  license_valid_till DATE,

  -- cached store metrics (optional)
  rating_avg   NUMERIC(3,2),
  rating_count INT,
  orders_30d   INT,

  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(owner_user_id, role)
);

CREATE INDEX ix_provider_stores_role ON provider_stores(role);
CREATE INDEX ix_provider_stores_city ON provider_stores(city);

DROP TRIGGER IF EXISTS touch_provider_stores ON provider_stores;
CREATE TRIGGER touch_provider_stores
BEFORE UPDATE ON provider_stores
FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();

CREATE TABLE store_badges (
  id SERIAL PRIMARY KEY,
  store_id INT NOT NULL REFERENCES provider_stores(id) ON DELETE CASCADE,
  badge TEXT NOT NULL,
  UNIQUE(store_id, badge)
);

CREATE INDEX ix_store_badges_store ON store_badges(store_id);


-- =========================================================
-- 3) BRANDS
-- =========================================================
DROP TABLE IF EXISTS brands CASCADE;

CREATE TABLE brands (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  about TEXT,
  logo_uri TEXT,
  website TEXT
);


-- =========================================================
-- 4) TAX / GST
-- =========================================================
DROP TABLE IF EXISTS tax_classes CASCADE;

CREATE TABLE tax_classes (
  code TEXT PRIMARY KEY,                 -- e.g. GST_0, GST_5, GST_12, GST_18
  gst_pct NUMERIC(5,2) NOT NULL CHECK (gst_pct >= 0),
  description TEXT
);


-- =========================================================
-- 5) CATALOG: PRODUCTS + SKUS (VARIANTS)
-- =========================================================
DROP TABLE IF EXISTS product_tags CASCADE;
DROP TABLE IF EXISTS product_media CASCADE;
DROP TABLE IF EXISTS product_specs CASCADE;
DROP TABLE IF EXISTS catalog_skus CASCADE;
DROP TABLE IF EXISTS catalog_products CASCADE;

CREATE TABLE catalog_products (
  id            SERIAL PRIMARY KEY,

  category      TEXT NOT NULL CHECK (category IN ('FOOD','ACCESSORY','MEDICINE','SERVICE')),
  brand_id      INT REFERENCES brands(id) ON DELETE SET NULL,
  brand_text    TEXT,  -- fallback if no brand row

  title         TEXT NOT NULL,
  short_desc    TEXT,         -- bullet-ish short copy
  description   TEXT,         -- long description
  about_brand   TEXT,         -- override if needed (else from brands.about)

  prescription_required BOOLEAN NOT NULL DEFAULT FALSE,

  -- tax classification
  hsn_code      TEXT,
  tax_class     TEXT REFERENCES tax_classes(code),

  -- variant theme hints (optional)
  variant_theme TEXT,         -- "Color", "Size", "Flavour"
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_catalog_products_category ON catalog_products(category);
CREATE INDEX ix_catalog_products_brand_id ON catalog_products(brand_id);
CREATE INDEX ix_catalog_products_active ON catalog_products(is_active);

DROP TRIGGER IF EXISTS touch_catalog_products ON catalog_products;
CREATE TRIGGER touch_catalog_products
BEFORE UPDATE ON catalog_products
FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();


-- One row per purchasable variant (SKU)
CREATE TABLE catalog_skus (
  id            SERIAL PRIMARY KEY,
  product_id    INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,

  variant_key   TEXT,         -- "Color"
  variant_value TEXT,         -- "Yellow"
  pack_label    TEXT,         -- "900ml", "1.1kg", "Pack of 12"

  sku_code      TEXT UNIQUE,
  barcode       TEXT,

  sort_order    INT NOT NULL DEFAULT 0,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_skus_product ON catalog_skus(product_id, sort_order);
CREATE INDEX ix_skus_variant ON catalog_skus(product_id, variant_key, sort_order);
CREATE INDEX ix_skus_active ON catalog_skus(is_active);


-- Product images/videos (PDP carousel)
CREATE TABLE product_media (
  id         SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  media_type TEXT NOT NULL DEFAULT 'IMAGE' CHECK (media_type IN ('IMAGE','VIDEO')),
  uri        TEXT NOT NULL,
  label      TEXT,
  sort_order INT NOT NULL DEFAULT 0
);

CREATE INDEX ix_product_media_product ON product_media(product_id, sort_order);


-- Specs with grouping (Top highlights / Product details / etc.)
CREATE TABLE product_specs (
  id         SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  spec_group TEXT NOT NULL DEFAULT 'General',
  spec_key   TEXT NOT NULL,
  spec_value TEXT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0
);

CREATE INDEX ix_product_specs_product ON product_specs(product_id, spec_group, sort_order);


-- Tags (for browse + similar + explore)
CREATE TABLE product_tags (
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  tag        TEXT NOT NULL,
  PRIMARY KEY(product_id, tag)
);

CREATE INDEX ix_product_tags_tag ON product_tags(tag);


-- =========================================================
-- 6) STORE OFFERS: store sells a SKU (price/mrp/stock/promise)
-- =========================================================
DROP TABLE IF EXISTS store_offers CASCADE;

CREATE TABLE store_offers (
  id           SERIAL PRIMARY KEY,

  store_id     INT NOT NULL REFERENCES provider_stores(id) ON DELETE CASCADE,
  sku_id       INT NOT NULL REFERENCES catalog_skus(id) ON DELETE CASCADE,

  is_active    BOOLEAN NOT NULL DEFAULT TRUE,

  currency     TEXT NOT NULL DEFAULT 'INR',
  price        NUMERIC(12,2) NOT NULL DEFAULT 0,
  mrp          NUMERIC(12,2),
  discount_pct INT CHECK (discount_pct BETWEEN 0 AND 95),

  stock_qty     INT NOT NULL DEFAULT 0,
  reorder_level INT NOT NULL DEFAULT 0,

  -- fulfillment promise
  shipping_fee NUMERIC(12,2),
  eta_text     TEXT,
  eta_days_min INT,
  eta_days_max INT,
  returnable   BOOLEAN,
  warranty_months INT,

  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(store_id, sku_id)
);

CREATE INDEX ix_store_offers_store ON store_offers(store_id);
CREATE INDEX ix_store_offers_sku ON store_offers(sku_id);
CREATE INDEX ix_store_offers_active ON store_offers(is_active) WHERE is_active=TRUE;
CREATE INDEX ix_store_offers_instock ON store_offers(store_id, stock_qty) WHERE stock_qty > 0;


-- =========================================================
-- 7) PROMOTIONS (Deals/Coupons/Bank/Bundles)
-- =========================================================
DROP TABLE IF EXISTS promotion_targets CASCADE;
DROP TABLE IF EXISTS promotions CASCADE;

CREATE TABLE promotions (
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  subtitle TEXT,

  promo_type TEXT NOT NULL CHECK (promo_type IN ('DISCOUNT','COUPON','BANK','BUNDLE')),
  discount_pct INT CHECK (discount_pct BETWEEN 0 AND 95),
  discount_amount NUMERIC(12,2) CHECK (discount_amount >= 0),

  min_qty INT NOT NULL DEFAULT 1 CHECK (min_qty >= 1),

  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE promotion_targets (
  id SERIAL PRIMARY KEY,
  promo_id INT NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
  store_offer_id INT NOT NULL REFERENCES store_offers(id) ON DELETE CASCADE,
  UNIQUE(promo_id, store_offer_id)
);

CREATE INDEX ix_promo_targets_offer ON promotion_targets(store_offer_id);


-- =========================================================
-- 8) CART + ORDERS + ORDER ITEMS (for bought-in-month + invoices)
-- =========================================================
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS cart_items CASCADE;
DROP TABLE IF EXISTS carts CASCADE;

CREATE TABLE carts (
  id SERIAL PRIMARY KEY,
  parent_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  address_id INT REFERENCES user_addresses(id) ON DELETE SET NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(parent_user_id)
);

DROP TRIGGER IF EXISTS touch_carts ON carts;
CREATE TRIGGER touch_carts
BEFORE UPDATE ON carts
FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();

CREATE TABLE cart_items (
  id SERIAL PRIMARY KEY,
  cart_id INT NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
  store_offer_id INT NOT NULL REFERENCES store_offers(id) ON DELETE RESTRICT,
  qty INT NOT NULL CHECK (qty >= 1),

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(cart_id, store_offer_id)
);

CREATE INDEX ix_cart_items_cart ON cart_items(cart_id);

DROP TRIGGER IF EXISTS touch_cart_items ON cart_items;
CREATE TRIGGER touch_cart_items
BEFORE UPDATE ON cart_items
FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();


CREATE TABLE orders (
  id SERIAL PRIMARY KEY,

  parent_user_id INT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  store_id INT NOT NULL REFERENCES provider_stores(id) ON DELETE RESTRICT,
  address_id INT NOT NULL REFERENCES user_addresses(id) ON DELETE RESTRICT,

  status TEXT NOT NULL CHECK (status IN ('CREATED','CONFIRMED','PACKED','DISPATCHED','DELIVERED','CANCELLED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  currency TEXT NOT NULL DEFAULT 'INR',
  items_total NUMERIC(12,2) NOT NULL DEFAULT 0,
  discount_total NUMERIC(12,2) NOT NULL DEFAULT 0,
  shipping_fee NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_total NUMERIC(12,2) NOT NULL DEFAULT 0,
  grand_total NUMERIC(12,2) NOT NULL DEFAULT 0,

  invoice_no TEXT,
  invoice_created_at TIMESTAMPTZ
);

CREATE INDEX ix_orders_parent_created ON orders(parent_user_id, created_at DESC);
CREATE INDEX ix_orders_store_created ON orders(store_id, created_at DESC);

CREATE TABLE order_items (
  id SERIAL PRIMARY KEY,
  order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,

  store_offer_id INT NOT NULL REFERENCES store_offers(id) ON DELETE RESTRICT,
  sku_id INT NOT NULL REFERENCES catalog_skus(id) ON DELETE RESTRICT,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE RESTRICT,

  title_snapshot TEXT NOT NULL,
  variant_snapshot TEXT,

  qty INT NOT NULL CHECK (qty >= 1),

  unit_price NUMERIC(12,2) NOT NULL,
  mrp NUMERIC(12,2),
  discount_amt NUMERIC(12,2) NOT NULL DEFAULT 0,

  gst_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
  gst_amt NUMERIC(12,2) NOT NULL DEFAULT 0,

  line_total NUMERIC(12,2) NOT NULL DEFAULT 0
);

CREATE INDEX ix_order_items_order ON order_items(order_id);
CREATE INDEX ix_order_items_product ON order_items(product_id);


-- =========================================================
-- 9) PRODUCT REVIEWS + MEDIA + HELPFUL VOTES
-- =========================================================
DROP TABLE IF EXISTS review_votes CASCADE;
DROP TABLE IF EXISTS review_media CASCADE;
DROP TABLE IF EXISTS item_reviews CASCADE;

CREATE TABLE item_reviews (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  sku_id INT REFERENCES catalog_skus(id) ON DELETE SET NULL,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title TEXT,
  body TEXT NOT NULL,

  is_verified_purchase BOOLEAN NOT NULL DEFAULT FALSE,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(product_id, user_id)
);

CREATE INDEX ix_reviews_product_time ON item_reviews(product_id, created_at DESC);

CREATE TABLE review_media (
  id SERIAL PRIMARY KEY,
  review_id INT NOT NULL REFERENCES item_reviews(id) ON DELETE CASCADE,
  media_type TEXT NOT NULL DEFAULT 'IMAGE' CHECK (media_type IN ('IMAGE','VIDEO')),
  uri TEXT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0
);

CREATE INDEX ix_review_media_review ON review_media(review_id, sort_order);

-- helpful votes: 1 row per user per review
CREATE TABLE review_votes (
  id SERIAL PRIMARY KEY,
  review_id INT NOT NULL REFERENCES item_reviews(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  is_helpful BOOLEAN NOT NULL, -- true=helpful, false=not helpful
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(review_id, user_id)
);

CREATE INDEX ix_review_votes_review ON review_votes(review_id);


-- =========================================================
-- 10) STORE REVIEWS (separate from product reviews)
-- =========================================================
DROP TABLE IF EXISTS store_review_votes CASCADE;
DROP TABLE IF EXISTS store_reviews CASCADE;

CREATE TABLE store_reviews (
  id SERIAL PRIMARY KEY,
  store_id INT NOT NULL REFERENCES provider_stores(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title TEXT,
  body TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(store_id, user_id)
);

CREATE INDEX ix_store_reviews_store_time ON store_reviews(store_id, created_at DESC);

CREATE TABLE store_review_votes (
  id SERIAL PRIMARY KEY,
  review_id INT NOT NULL REFERENCES store_reviews(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  is_helpful BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(review_id, user_id)
);


-- =========================================================
-- 11) Q/A
-- =========================================================
DROP TABLE IF EXISTS item_answers CASCADE;
DROP TABLE IF EXISTS item_questions CASCADE;

CREATE TABLE item_questions (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE item_answers (
  id SERIAL PRIMARY KEY,
  question_id INT NOT NULL REFERENCES item_questions(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  answer TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_questions_product_time ON item_questions(product_id, created_at DESC);


-- =========================================================
-- 12) WISHLIST (product-level)
-- =========================================================
DROP TABLE IF EXISTS wishlist_items CASCADE;
DROP TABLE IF EXISTS wishlists CASCADE;

CREATE TABLE wishlists (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id)
);

CREATE TABLE wishlist_items (
  id SERIAL PRIMARY KEY,
  wishlist_id INT NOT NULL REFERENCES wishlists(id) ON DELETE CASCADE,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(wishlist_id, product_id)
);

CREATE INDEX ix_wishlist_items_wishlist ON wishlist_items(wishlist_id);


-- =========================================================
-- 13) RECOMMENDATIONS: curated + signals
-- =========================================================
DROP TABLE IF EXISTS user_item_events CASCADE;
DROP TABLE IF EXISTS item_relations CASCADE;

-- curated relations between products
CREATE TABLE item_relations (
  id SERIAL PRIMARY KEY,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  related_product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,

  relation_type TEXT NOT NULL CHECK (relation_type IN ('SIMILAR','ALSO_LIKE','FBT')),
  weight INT NOT NULL DEFAULT 100,

  UNIQUE(product_id, related_product_id, relation_type)
);

CREATE INDEX ix_item_relations_product_type ON item_relations(product_id, relation_type, weight DESC);

-- behavioral events for ML later + quick analytics now
CREATE TABLE user_item_events (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id) ON DELETE SET NULL,
  product_id INT NOT NULL REFERENCES catalog_products(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (event_type IN ('VIEW','ADD_TO_CART','WISHLIST','PURCHASE')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX ix_events_product_time ON user_item_events(product_id, created_at DESC);
CREATE INDEX ix_events_user_time ON user_item_events(user_id, created_at DESC);

ALTER TABLE vet_profiles
DROP CONSTRAINT vet_profiles_slot_minutes_check;

ALTER TABLE vet_profiles
ADD CONSTRAINT vet_profiles_slot_minutes_check
CHECK (slot_minutes > 0);

ALTER TABLE catalog_products
ADD COLUMN created_by_store_id INT NULL REFERENCES provider_stores(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_catalog_products_created_by_store
ON catalog_products(created_by_store_id);

ALTER TABLE provider_stores
  DROP CONSTRAINT IF EXISTS provider_stores_owner_user_id_role_key;

-- if it is an index instead:
DROP INDEX IF EXISTS provider_stores_owner_user_id_role_key;

-- optionally add a non-unique index for query speed
CREATE INDEX IF NOT EXISTS ix_provider_stores_owner_role
  ON provider_stores(owner_user_id, role);