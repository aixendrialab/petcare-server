-- seed.sql (no orgs)

-- Users (Asha has parent+vet; active role set to parent)
INSERT INTO users (id, phone, email, name, active_role) VALUES
  (1, '+919999', 'asha@example.com',         'Asha Rao',       'parent'),
  (2, '+918888',  'krish@example.com',        'Krish Malhotra', NULL),
  (3, '+917777',  'meera.shah@pawsclinic.com','Dr. Meera Shah', 'vet')
ON CONFLICT (id) DO NOTHING;

-- Roles
INSERT INTO user_roles (user_id, role) VALUES
  (1, 'parent'),
  (1, 'vet'),
  (2, 'parent'),
  (3, 'vet')
ON CONFLICT DO NOTHING;

-- Pets (Asha has two)
INSERT INTO pets (user_id, name, breed, gender, vaccine_status, rewards, picture_uri, dob) VALUES
  (1, 'Bruno', 'Labrador', 'male', 'up_to_date', 'Best Boi', 'https://picsum.photos/seed/bruno/200', '2022-06-15'),
  (1, 'Misty', 'Persian Cat', 'female', 'due', 'Cutest Napper', 'https://picsum.photos/seed/misty/200', '2021-09-01')
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role)
SELECT 1, 'vet'
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id=1 AND role='vet');

INSERT INTO user_roles (user_id, role)
SELECT 3, 'vet'
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id=3 AND role='vet');

-- Vet profiles for those users
INSERT INTO vet_profiles (
  user_id, legal_name, display_name, business_email, billing_email, billing_address,
  gstin, pan, qualifications, license_no, experience_years, specialties,
  visit_in_clinic, visit_video, fee_in_clinic, fee_video, slot_minutes
) VALUES
  (1, 'Paws Care LLP', 'Dr. Asha Rao', 'billing@pawscare.in', NULL,
     '42, 2nd Main Rd\nAdyar\nChennai 600020', '33AAAAA0000A1Z5', NULL,
     'BVSc & AH', 'TN-VA-001', 5, '["dermatology","wellness"]',
     TRUE, TRUE, 600, 500, 15),
  (3, 'Paws Clinic', 'Dr. Meera Shah', 'accounts@pawsclinic.com', 'billing@pawsclinic.com',
     '8, Lake View\nVastrapur\nAhmedabad 380015', '24BBBBB1111B2Z6', 'ABCDE1234F',
     'BVSc & AH, MVSc (Surgery)', 'GJ-VA-9876', 12, '["surgery","orthopedics"]',
     TRUE, TRUE, 800, 700, 15)
ON CONFLICT (user_id) DO NOTHING;

-- Locations
INSERT INTO vet_locations (id, user_id, name, line1, line2, city, lat, lng, hours, is_primary) VALUES
  (101, 1, 'Paws Care – Adyar', '42, 2nd Main Rd', 'LB Rd', 'Chennai', 13.0001, 80.2663, 'Mon–Sat 09:00–18:00', TRUE),
  (102, 1, 'Video (Virtual)', 'online', '—', '-',  13.0001, 80.2663, 'Mon–Fri 14:00–17:00', false),
  (103, 3, 'Paws Clinic – Vastrapur', '8 Lake View', NULL, 'Ahmedabad', 23.0356, 72.5293, 'Mon–Sat 10:00–19:00', TRUE)
ON CONFLICT DO NOTHING;


-- Sync sequences to current max IDs after seeding
SELECT setval(pg_get_serial_sequence('users','id'),      COALESCE((SELECT MAX(id) FROM users),0)+1, false);
SELECT setval(pg_get_serial_sequence('user_roles','id'), COALESCE((SELECT MAX(id) FROM user_roles),0)+1, false);
SELECT setval(pg_get_serial_sequence('pets','id'),       COALESCE((SELECT MAX(id) FROM pets),0)+1, false);
SELECT setval(pg_get_serial_sequence('vet_locations','id'), COALESCE((SELECT MAX(id) FROM vet_locations),0)+1, false);

-- In-person baseline (Mon–Fri 9–12 with a break 10:00–10:30)
INSERT INTO slot_settings (
  user_id, location_id, consultation_type,
  slot_minutes, gap_minutes, per_slot_capacity, lead_time_minutes, booking_window_days,
  visible_to_parents, week_rules, blackout_dates, effective_from, effective_to
) VALUES (
  1, 101, 'in_person',
  30, 10, 1, 0, 25,
  TRUE,
  '{
     "mon":[{"start":"09:00","end":"12:00","breaks":[{"start":"10:00","end":"10:30"}]}],
     "tue":[{"start":"09:00","end":"12:00"}],
     "wed":[{"start":"09:00","end":"12:00"}],
     "thu":[{"start":"09:00","end":"12:00"}],
     "fri":[{"start":"09:00","end":"12:00"}],
     "sat":[], "sun":[]
   }',
  '[]',
  NULL, NULL
) ON CONFLICT DO NOTHING;

-- Video baseline (Mon–Fri 14–17)
INSERT INTO slot_settings (
  user_id, location_id, consultation_type,
  slot_minutes, gap_minutes, per_slot_capacity, lead_time_minutes, booking_window_days,
  visible_to_parents, week_rules, blackout_dates, effective_from, effective_to
) VALUES (
  1, 102, 'video',
  15, 5, 1, 60, 14,
  TRUE,
  '{
     "mon":[{"start":"14:00","end":"17:00"}],
     "tue":[{"start":"14:00","end":"17:00"}],
     "wed":[{"start":"14:00","end":"17:00"}],
     "thu":[{"start":"14:00","end":"17:00"}],
     "fri":[{"start":"14:00","end":"17:00"}],
     "sat":[], "sun":[]
   }',
  '[]',
  NULL, NULL
) ON CONFLICT DO NOTHING;

-- =========================
-- Seed slot_overrides
-- =========================

-- A) In-person: TODAY block 15:00–16:00
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE, '{"block_windows":[{"start":"15:00","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- B) In-person: TOMORROW replace day with 11:00–16:00
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '1 day',
       '{"open_windows":[{"start":"11:00","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- C) In-person: DAY+2 capacity=2 from 10:00–11:00
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '2 day',
       '{"capacity_overrides":[{"start":"10:00","end":"11:00","capacity":2}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- D) In-person: DAY+3 add extra 18:00–19:00 (10-min rapid slots)
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '3 day',
       '{"extra_slots":[{"start":"18:00","end":"19:00","slot_minutes":10,"capacity":1}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- E) Video: TODAY block 15:30–16:00
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE, '{"block_windows":[{"start":"15:30","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- F) Video: DAY+1 add extra 17:00–17:30 with 10-min
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '1 day',
       '{"extra_slots":[{"start":"17:00","end":"17:30","slot_minutes":10,"capacity":1}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- G) Video: DAY+2 replace day with 13:00–15:00
WITH s AS (
  SELECT id FROM slot_settings
  WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '2 day',
       '{"open_windows":[{"start":"13:00","end":"15:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- =========================================================
-- VACCINATION MASTER + PLAN + HISTORY SEED (INTEGRATED)
-- =========================================================

-- ---------------------------------------------------------
-- 0) Ensure pets have species (required everywhere)
-- ---------------------------------------------------------
UPDATE pets SET species='dog'
WHERE name='Bruno' AND (species IS NULL OR species='');

UPDATE pets SET species='cat'
WHERE name='Misty' AND (species IS NULL OR species='');

-- ---------------------------------------------------------
-- 1) Vaccine Catalog (Admin-controlled master)
-- ---------------------------------------------------------
INSERT INTO vaccine_catalog (code, species, name, vaccine_type, description, is_active) VALUES

-- DOG – CORE
('DHPP','dog','DHPP / DHPPi (Distemper, Hepatitis, Parvo, Parainfluenza)','core',
 'Primary puppy series + booster', TRUE),
('RABIES','dog','Rabies','core',
 'Rabies vaccination', TRUE),

-- DOG – OPTIONAL / RISK BASED
('LEPTO','dog','Leptospirosis','optional','Often annual; risk-based', TRUE),
('KC','dog','Kennel Cough (Bordetella)','optional','Boarding/grooming requirement', TRUE),
('CORONA','dog','Canine Coronavirus','optional','Risk-based', TRUE),
('LYME','dog','Lyme','optional','Tick-risk regions', TRUE),

-- CAT – CORE
('FVRCP','cat','FVRCP (Feline Viral Rhinotracheitis, Calici, Panleukopenia)','core',
 'Kitten series + booster', TRUE),
('RABIES','cat','Rabies','core',
 'Rabies vaccination', TRUE),

-- CAT – OPTIONAL
('FELV','cat','FeLV (Feline Leukemia Virus)','optional',
 'Risk-based; kittens / outdoor cats', TRUE),
('FIV','cat','FIV (Feline Immunodeficiency Virus)','optional',
 'Rarely used; availability varies', TRUE)

ON CONFLICT (code, species) DO NOTHING;


-- ---------------------------------------------------------
-- 2) Vaccine Rules (Default schedule recipes)
-- ---------------------------------------------------------

-- DOG rules
INSERT INTO vaccine_rule (
  species, vaccine_id,
  start_age_weeks, dose_count, dose_interval_days, booster_interval_days,
  is_active
)
SELECT 'dog', c.id, 6, 3, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='DHPP' AND c.species='dog'
UNION ALL
SELECT 'dog', c.id, 12, 1, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='RABIES' AND c.species='dog'
UNION ALL
SELECT 'dog', c.id, 12, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='LEPTO' AND c.species='dog'
UNION ALL
SELECT 'dog', c.id, 12, 1, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='KC' AND c.species='dog'
UNION ALL
SELECT 'dog', c.id, 12, 1, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='CORONA' AND c.species='dog'
UNION ALL
SELECT 'dog', c.id, 12, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='LYME' AND c.species='dog'
ON CONFLICT DO NOTHING;

-- CAT rules
INSERT INTO vaccine_rule (
  species, vaccine_id,
  start_age_weeks, dose_count, dose_interval_days, booster_interval_days,
  is_active
)
SELECT 'cat', c.id, 6, 3, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FVRCP' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 12, 1, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='RABIES' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 8, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FELV' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 12, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FIV' AND c.species='cat'
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------
-- 3) Create vaccine plans for seeded pets
-- ---------------------------------------------------------
INSERT INTO pet_vaccine_plan (pet_id, status, generated_at, notes)
SELECT p.id, 'SUGGESTED', now(), 'Seeded vaccination plan'
FROM pets p
WHERE p.name IN ('Bruno','Misty')
ON CONFLICT (pet_id) DO NOTHING;


-- ---------------------------------------------------------
-- 4) Plan items – Bruno (Dog)
-- ---------------------------------------------------------
WITH plan AS (
  SELECT pp.id AS plan_id
  FROM pet_vaccine_plan pp
  JOIN pets p ON p.id = pp.pet_id
  WHERE p.name='Bruno'
)
INSERT INTO pet_vaccine_plan_item (
  plan_id, vaccine_id, vaccine_code, vaccine_species,
  dose_no, due_on, status
)
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 3, 'DUE'
FROM plan JOIN vaccine_catalog c ON c.code='DHPP' AND c.species='dog'
UNION ALL
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 20, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='RABIES' AND c.species='dog'
UNION ALL
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 35, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='LEPTO' AND c.species='dog'
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------
-- 5) Plan items – Misty (Cat)
-- ---------------------------------------------------------
WITH plan AS (
  SELECT pp.id AS plan_id
  FROM pet_vaccine_plan pp
  JOIN pets p ON p.id = pp.pet_id
  WHERE p.name='Misty'
)
INSERT INTO pet_vaccine_plan_item (
  plan_id, vaccine_id, vaccine_code, vaccine_species,
  dose_no, due_on, status
)
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 10, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='FVRCP' AND c.species='cat'
UNION ALL
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 1, 'DUE'
FROM plan JOIN vaccine_catalog c ON c.code='RABIES' AND c.species='cat'
UNION ALL
SELECT plan.plan_id, c.id, c.code, c.species, 0, CURRENT_DATE + 28, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='FELV' AND c.species='cat'
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------
-- 6) One completed vaccination record (history demo)
-- ---------------------------------------------------------
WITH bruno AS (
  SELECT p.id AS pet_id FROM pets p WHERE p.name='Bruno'
),
rec AS (
  INSERT INTO vaccination_record (
    pet_id, vaccine_id, vaccine_code, vaccine_species,
    vaccine_type, last_given, next_due,
    notes, vet_id, location_id
  )
  SELECT
    b.pet_id,
    c.id,
    c.code,
    c.species,
    'core',
    CURRENT_DATE - 365,
    CURRENT_DATE + 3,
    'Seeded completed DHPP',
    1,
    101
  FROM bruno b
  JOIN vaccine_catalog c ON c.code='DHPP' AND c.species='dog'
  RETURNING id
)
UPDATE pet_vaccine_plan_item pi
SET status='COMPLETED',
    completed_on=CURRENT_DATE - 365,
    completed_record_id=(SELECT id FROM rec)
WHERE pi.id = (
  SELECT pi2.id
  FROM pet_vaccine_plan_item pi2
  JOIN pet_vaccine_plan pp ON pp.id = pi2.plan_id
  JOIN pets p ON p.id = pp.pet_id
  WHERE p.name='Bruno'
    AND pi2.vaccine_code='DHPP'
  ORDER BY pi2.due_on
  LIMIT 1
);


-- ---------------------------------------------------------
-- 7) Sync sequences (clean state)
-- ---------------------------------------------------------
SELECT setval(pg_get_serial_sequence('vaccine_catalog','id'),
  COALESCE((SELECT MAX(id) FROM vaccine_catalog),0)+1, false);

SELECT setval(pg_get_serial_sequence('vaccine_rule','id'),
  COALESCE((SELECT MAX(id) FROM vaccine_rule),0)+1, false);

SELECT setval(pg_get_serial_sequence('pet_vaccine_plan','id'),
  COALESCE((SELECT MAX(id) FROM pet_vaccine_plan),0)+1, false);

SELECT setval(pg_get_serial_sequence('pet_vaccine_plan_item','id'),
  COALESCE((SELECT MAX(id) FROM pet_vaccine_plan_item),0)+1, false);

SELECT setval(pg_get_serial_sequence('vaccination_record','id'),
  COALESCE((SELECT MAX(id) FROM vaccination_record),0)+1, false);

INSERT INTO user_roles (user_id, role)
SELECT 1, 'vendor'
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id=1 AND role='vendor');

-- Vendor store for user 1 (Asha)
INSERT INTO provider_stores (owner_user_id, role, display_name, phone, city, state, pincode, status)
VALUES (1, 'vendor', 'Asha Pet Supplies', '+919999', 'Vizag', 'AP', '530001', 'ACTIVE')
ON CONFLICT (owner_user_id, role) DO NOTHING;

-- Another vendor user + store (so parent can see “other sellers”)
INSERT INTO users (id, phone, email, name, active_role)
VALUES (4, '+916666', 'vendor2@example.com', 'Ravi Vendor', 'vendor')
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_roles (user_id, role)
VALUES (4, 'vendor')
ON CONFLICT DO NOTHING;

INSERT INTO provider_stores (owner_user_id, role, display_name, phone, city, state, pincode, status)
VALUES (4, 'vendor', 'Ravi Pet Mart', '+916666', 'Vizag', 'AP', '530016', 'ACTIVE')
ON CONFLICT (owner_user_id, role) DO NOTHING;

-- Grab store ids
WITH s AS (
  SELECT id FROM provider_stores WHERE owner_user_id=4 AND role='vendor'
)
INSERT INTO store_items (store_id, title, description, category, brand, image_uri, price, currency, is_active)
SELECT s.id, 'Royal Canin Adult 2kg', 'Dry food for adult dogs', 'FOOD', 'Royal Canin',
       'https://picsum.photos/seed/rc/300', 1299, 'INR', TRUE
FROM s
ON CONFLICT DO NOTHING;

WITH s AS (
  SELECT id FROM provider_stores WHERE owner_user_id=4 AND role='vendor'
),
it AS (
  SELECT id AS item_id, store_id FROM store_items WHERE title='Royal Canin Adult 2kg'
)
INSERT INTO store_inventory (store_id, catalog_item_id, stock_qty, reorder_level)
SELECT it.store_id, it.item_id, 25, 5 FROM it
ON CONFLICT (store_id, catalog_item_id) DO NOTHING;
