-- =========================================================
-- seed.sql (NO ORGS) — FIXED for vaccine_catalog.id PK
-- + Rich shop seeding (lots of items + inventory across vendors/pharmacy)
-- =========================================================

-- -------------------------
-- Users
-- -------------------------
INSERT INTO users (id, phone, email, name, active_role) VALUES
  (1, '+919999', 'asha@example.com',          'Asha Rao',        'parent'),
  (2, '+918888', 'krish@example.com',         'Krish Malhotra',  NULL),
  (3, '+917777', 'meera.shah@pawsclinic.com', 'Dr. Meera Shah',  'vet'),
  (4, '+916666', 'vendor2@example.com',       'Ravi Vendor',     'vendor'),
  (5, '+915555', 'pharma@example.com',        'Sita Pharmacist', 'pharmacist'),
  (6, '+914444', 'groomer@example.com',       'Kiran Groomer',   'vendor')
ON CONFLICT (id) DO NOTHING;

-- -------------------------
-- Roles
-- -------------------------
INSERT INTO user_roles (user_id, role) VALUES
  (1, 'parent'),
  (1, 'vet'),
  (2, 'parent'),
  (3, 'vet'),
  (4, 'vendor'),
  (5, 'pharmacist'),
  (6, 'vendor')
ON CONFLICT DO NOTHING;

-- -------------------------
-- Pets
-- -------------------------
INSERT INTO pets (user_id, name, breed, gender, vaccine_status, rewards, picture_uri, dob, species) VALUES
  (1, 'Bruno', 'Labrador',    'male',   'up_to_date', 'Best Boi',      'https://picsum.photos/seed/bruno/400', '2022-06-15', 'dog'),
  (1, 'Misty', 'Persian Cat', 'female', 'due',        'Cutest Napper', 'https://picsum.photos/seed/misty/400', '2021-09-01', 'cat')
ON CONFLICT DO NOTHING;

-- -------------------------
-- Vet Profiles
-- -------------------------
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

-- -------------------------
-- Vet Locations
-- -------------------------
INSERT INTO vet_locations (id, user_id, name, line1, line2, city, lat, lng, hours, is_primary) VALUES
  (101, 1, 'Paws Care – Adyar',        '42, 2nd Main Rd', 'LB Rd', 'Chennai',    13.0001, 80.2663, 'Mon–Sat 09:00–18:00', TRUE),
  (102, 1, 'Video (Virtual)',         'online',          '—',     '-',          13.0001, 80.2663, 'Mon–Fri 14:00–17:00', FALSE),
  (103, 3, 'Paws Clinic – Vastrapur', '8 Lake View',     NULL,    'Ahmedabad',  23.0356, 72.5293, 'Mon–Sat 10:00–19:00', TRUE)
ON CONFLICT DO NOTHING;

-- -------------------------
-- Sync sequences after seeding base IDs
-- -------------------------
SELECT setval(pg_get_serial_sequence('users','id'),           COALESCE((SELECT MAX(id) FROM users),0)+1, false);
SELECT setval(pg_get_serial_sequence('user_roles','id'),      COALESCE((SELECT MAX(id) FROM user_roles),0)+1, false);
SELECT setval(pg_get_serial_sequence('pets','id'),            COALESCE((SELECT MAX(id) FROM pets),0)+1, false);
SELECT setval(pg_get_serial_sequence('vet_locations','id'),   COALESCE((SELECT MAX(id) FROM vet_locations),0)+1, false);

-- =========================================================
-- SLOT SETTINGS + OVERRIDES (unchanged)
-- =========================================================

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

-- Overrides (same as your script)
WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE, '{"block_windows":[{"start":"15:00","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '1 day', '{"open_windows":[{"start":"11:00","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '2 day', '{"capacity_overrides":[{"start":"10:00","end":"11:00","capacity":2}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=101 AND consultation_type='in_person' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '3 day', '{"extra_slots":[{"start":"18:00","end":"19:00","slot_minutes":10,"capacity":1}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE, '{"block_windows":[{"start":"15:30","end":"16:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '1 day', '{"extra_slots":[{"start":"17:00","end":"17:30","slot_minutes":10,"capacity":1}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

WITH s AS (
  SELECT id FROM slot_settings WHERE user_id=1 AND location_id=102 AND consultation_type='video' LIMIT 1
)
INSERT INTO slot_overrides (slot_setting_id, "date", payload)
SELECT s.id, CURRENT_DATE + INTERVAL '2 day', '{"open_windows":[{"start":"13:00","end":"15:00"}]}'::jsonb
FROM s
ON CONFLICT (slot_setting_id, "date")
DO UPDATE SET payload = slot_overrides.payload || EXCLUDED.payload;

-- =========================================================
-- VACCINES — FIXED for vaccine_catalog.id PK + vaccine_rule depends on id
-- IMPORTANT: assumes schema has vaccine_catalog.id PK + uq(code,species)
-- and vaccine_rule has vaccine_id FK to vaccine_catalog(id)
-- If your pet_vaccine_plan_item / vaccination_record still include vaccine_code/species,
-- this seed still works, but it will always set vaccine_id correctly.
-- =========================================================

-- 1) Vaccine Catalog
INSERT INTO vaccine_catalog (code, species, name, vaccine_type, description, is_active) VALUES
('DHPP','dog','DHPP / DHPPi (Distemper, Hepatitis, Parvo, Parainfluenza)','core','Primary puppy series + booster', TRUE),
('RABIES','dog','Rabies','core','Rabies vaccination', TRUE),
('LEPTO','dog','Leptospirosis','optional','Often annual; risk-based', TRUE),
('KC','dog','Kennel Cough (Bordetella)','optional','Boarding/grooming requirement', TRUE),
('CORONA','dog','Canine Coronavirus','optional','Risk-based', TRUE),
('LYME','dog','Lyme','optional','Tick-risk regions', TRUE),
('FVRCP','cat','FVRCP (Feline Viral Rhinotracheitis, Calici, Panleukopenia)','core','Kitten series + booster', TRUE),
('RABIES','cat','Rabies','core','Rabies vaccination', TRUE),
('FELV','cat','FeLV (Feline Leukemia Virus)','optional','Risk-based; kittens / outdoor cats', TRUE),
('FIV','cat','FIV (Feline Immunodeficiency Virus)','optional','Rarely used; availability varies', TRUE)
ON CONFLICT (code, species) DO NOTHING;

-- 2) Vaccine Rules (depends on vaccine_catalog.id)
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
UNION ALL
SELECT 'cat', c.id, 6, 3, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FVRCP' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 12, 1, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='RABIES' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 8, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FELV' AND c.species='cat'
UNION ALL
SELECT 'cat', c.id, 12, 2, 21, 365, TRUE FROM vaccine_catalog c WHERE c.code='FIV' AND c.species='cat'
ON CONFLICT DO NOTHING;

-- 3) Create vaccine plans for seeded pets
INSERT INTO pet_vaccine_plan (pet_id, status, generated_at, notes)
SELECT p.id, 'SUGGESTED', now(), 'Seeded vaccination plan'
FROM pets p
WHERE p.name IN ('Bruno','Misty')
ON CONFLICT (pet_id) DO NOTHING;

-- 4) Plan items – Bruno (Dog)
WITH plan AS (
  SELECT pp.id AS plan_id
  FROM pet_vaccine_plan pp
  JOIN pets p ON p.id = pp.pet_id
  WHERE p.name='Bruno'
)
INSERT INTO pet_vaccine_plan_item (
  plan_id, vaccine_id, dose_no, due_on, status
)
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 3,  'DUE'
FROM plan JOIN vaccine_catalog c ON c.code='DHPP' AND c.species='dog'
UNION ALL
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 20, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='RABIES' AND c.species='dog'
UNION ALL
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 35, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='LEPTO' AND c.species='dog'
ON CONFLICT DO NOTHING;

-- 5) Plan items – Misty (Cat)
WITH plan AS (
  SELECT pp.id AS plan_id
  FROM pet_vaccine_plan pp
  JOIN pets p ON p.id = pp.pet_id
  WHERE p.name='Misty'
)
INSERT INTO pet_vaccine_plan_item (
  plan_id, vaccine_id, dose_no, due_on, status
)
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 10, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='FVRCP' AND c.species='cat'
UNION ALL
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 1,  'DUE'
FROM plan JOIN vaccine_catalog c ON c.code='RABIES' AND c.species='cat'
UNION ALL
SELECT plan.plan_id, c.id, 1, CURRENT_DATE + 28, 'UPCOMING'
FROM plan JOIN vaccine_catalog c ON c.code='FELV' AND c.species='cat'
ON CONFLICT DO NOTHING;

-- 6) Completed vaccination record demo (Bruno DHPP) + mark earliest DHPP plan item completed
WITH bruno AS (
  SELECT p.id AS pet_id FROM pets p WHERE p.name='Bruno'
),
rec AS (
  INSERT INTO vaccination_record (
    pet_id, vaccine_id,
    vaccine_type, last_given, next_due,
    notes, vet_id, location_id
  )
  SELECT
    b.pet_id,
    c.id,
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
  JOIN vaccine_catalog vc ON vc.id = pi2.vaccine_id
  WHERE p.name='Bruno'
    AND vc.code='DHPP' AND vc.species='dog'
  ORDER BY pi2.due_on
  LIMIT 1
);

-- Sync sequences for vaccine tables
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

-- =========================================================
-- SHOP — provider stores + lots of items + inventory
-- (We keep it compatible with your current schema: provider_stores, store_items, store_inventory)
-- Images use picsum seeds (replace later with real CDN)
-- =========================================================

-- Ensure user 1 is vendor too (optional)
INSERT INTO user_roles (user_id, role)
SELECT 1, 'vendor'
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id=1 AND role='vendor');
-- =========================================================
-- SEED: COMMERCE v2 (Dog/Cat realistic) - EXPANDED
-- Assumes: users exist (ids 1..6) and commerce v2 schema is applied.
-- =========================================================

-- -------------------------
-- Tax classes (GST)
-- -------------------------
INSERT INTO tax_classes (code, gst_pct, description) VALUES
  ('GST_0',  0.00, 'Zero rated'),
  ('GST_5',  5.00, 'GST 5%'),
  ('GST_12', 12.00, 'GST 12%'),
  ('GST_18', 18.00, 'GST 18%')
ON CONFLICT (code) DO NOTHING;

-- -------------------------
-- Brands
-- -------------------------
INSERT INTO brands (name, about, logo_uri, website) VALUES
  ('Royal Canin', 'Breed and life-stage nutrition backed by scientific research.', NULL, NULL),
  ('Pedigree',    'Everyday dog nutrition and treats.', NULL, NULL),
  ('Whiskas',     'Complete nutrition for cats and kittens.', NULL, NULL),
  ('Drools',      'Dog nutrition and treats for Indian pet parents.', NULL, NULL),
  ('Himalaya Pet', 'Pet care range including shampoos and supplements.', NULL, NULL),
  ('PetCare',     'PetCare everyday essentials and accessories.', NULL, NULL),
  ('Goofy Tails', 'Fun toys and accessories for dogs and cats.', NULL, NULL),
  ('Groom & Glow', 'Professional grooming services.', NULL, NULL)
ON CONFLICT (name) DO NOTHING;

-- -------------------------
-- Stores
-- -------------------------
INSERT INTO provider_stores (
  owner_user_id, role, display_name, phone, email, logo_uri, about,
  status, address_line1, address_line2, city, state, pincode,
  license_no, license_valid_till
) VALUES
  (1, 'vendor',     'Asha Pet Supplies',   '+919999', 'store@asha.example.com', NULL,
   'Neighborhood pet store for food, toys, grooming essentials.', 'ACTIVE',
   'Dwaraka Nagar', 'Near RTC Complex', 'Vizag', 'AP', '530001', NULL, NULL),

  (4, 'vendor',     'Ravi Pet Mart',       '+916666', 'hello@ravipetmart.in', NULL,
   'Curated premium food, toys and accessories.', 'ACTIVE',
   'Madhurawada', 'Near IT SEZ', 'Vizag', 'AP', '530016', NULL, NULL),

  (5, 'pharmacist', 'Healthy Paws Pharma', '+915555', 'care@healthypaws.in', NULL,
   'Pharmacy for pet medicines and hygiene. Prescription where applicable.', 'ACTIVE',
   'MVP Colony', 'Near Bus Stop', 'Vizag', 'AP', '530048',
   'PHARMA-AP-2211', (CURRENT_DATE + INTERVAL '365 days')::date),

  (6, 'vendor',     'Groom & Glow',        '+914444', 'book@groomglow.in', NULL,
   'Bath, grooming and hygiene services by appointment.', 'ACTIVE',
   'Beach Road', 'Near Park', 'Vizag', 'AP', '530017', NULL, NULL)
ON CONFLICT (owner_user_id, role) DO NOTHING;

INSERT INTO store_badges (store_id, badge)
SELECT s.id, x.badge
FROM provider_stores s
JOIN (VALUES
  ('Asha Pet Supplies', 'Trusted seller'),
  ('Asha Pet Supplies', 'Great packaging'),
  ('Ravi Pet Mart', 'Fast dispatch'),
  ('Ravi Pet Mart', 'Premium selection'),
  ('Healthy Paws Pharma', 'Licensed pharmacy'),
  ('Healthy Paws Pharma', 'Authentic products'),
  ('Groom & Glow', 'Top rated service'),
  ('Groom & Glow', 'Hygiene first')
) x(store_name, badge)
  ON x.store_name = s.display_name
ON CONFLICT DO NOTHING;

-- -------------------------
-- Addresses
-- -------------------------
INSERT INTO user_addresses (
  user_id, label, recipient, phone,
  line1, line2, landmark, city, state, pincode,
  lat, lng, is_default
) VALUES
  (1, 'Home', 'Asha Rao', '+919999',
   'Flat 12B, Sunrise Apartments', 'Dwaraka Nagar', 'Near RTC Complex',
   'Vizag', 'AP', '530001', NULL, NULL, TRUE),

  (1, 'Office', 'Asha Rao', '+919999',
   'Unit 3A, Tech Park', 'Madhurawada', 'Near IT SEZ',
   'Vizag', 'AP', '530016', NULL, NULL, FALSE),

  (2, 'Home', 'Krish Malhotra', '+918888',
   '12, MVP Colony', 'Sector 4', 'Near Bus Stop',
   'Vizag', 'AP', '530048', NULL, NULL, TRUE)
ON CONFLICT DO NOTHING;

-- =========================================================
-- PRODUCTS (more variety)
-- =========================================================

-- Helper: insert product if missing
-- We use title uniqueness by convention in seed.
-- =========================================================

-- 1) Royal Canin Medium Adult
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'FOOD',
  (SELECT id FROM brands WHERE name='Royal Canin' LIMIT 1),
  'Royal Canin',
  'Royal Canin Medium Adult Dry Dog Food',
  'Complete nutrition for medium adult dogs (11–25 kg). Supports digestion, coat health, and immunity.',
  'Formulated for medium breed adult dogs. Balanced proteins and fibers help digestion. Omega fatty acids support skin and coat health.',
  FALSE, '23091000', 'GST_5', 'Size', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Royal Canin Medium Adult Dry Dog Food');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Size', '2 kg',  '2 kg',  'RC-MED-ADULT-2KG', 1, TRUE FROM catalog_products p WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
UNION ALL
SELECT p.id, 'Size', '4 kg',  '4 kg',  'RC-MED-ADULT-4KG', 2, TRUE FROM catalog_products p WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
UNION ALL
SELECT p.id, 'Size', '10 kg', '10 kg', 'RC-MED-ADULT-10KG',3, TRUE FROM catalog_products p WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,petfood?lock=1101', 'Front', 1
FROM catalog_products p WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
ON CONFLICT DO NOTHING;

INSERT INTO product_specs (product_id, spec_group, spec_key, spec_value, sort_order)
SELECT p.id, s.grp, s.k, s.v, s.ord
FROM catalog_products p
JOIN (VALUES
  ('Top highlights','Life stage','Adult (12+ months)',1),
  ('Top highlights','Breed size','Medium (11–25 kg)',2),
  ('Top highlights','Form','Dry kibble',3),
  ('Product details','Key benefits','Digestion support, coat health, immunity',10),
  ('Product details','Shelf life','18 months from MFG',11),
  ('Safety & care','Storage','Keep sealed; store in cool dry place',20)
) s(grp,k,v,ord) ON TRUE
WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('dog food'),('dry food'),('adult dog'),('medium breed'),('premium food')) t(tag) ON TRUE
WHERE p.title='Royal Canin Medium Adult Dry Dog Food'
ON CONFLICT DO NOTHING;


-- 2) Pedigree Adult Chicken (dog food)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'FOOD',
  (SELECT id FROM brands WHERE name='Pedigree' LIMIT 1),
  'Pedigree',
  'Pedigree Adult Dry Dog Food – Chicken & Vegetables',
  'Everyday complete nutrition for adult dogs. Supports healthy muscles and digestion.',
  'Pedigree adult dry food with chicken and vegetables. Balanced protein, vitamins and minerals for daily feeding.',
  FALSE, '23091000', 'GST_5', 'Size', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Pedigree Adult Dry Dog Food – Chicken & Vegetables');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Size', '1.2 kg', '1.2 kg', 'PD-ADULT-CHICK-1P2', 1, TRUE FROM catalog_products p WHERE p.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables'
UNION ALL
SELECT p.id, 'Size', '3 kg',   '3 kg',   'PD-ADULT-CHICK-3KG',  2, TRUE FROM catalog_products p WHERE p.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,petfood?lock=1102', 'Front', 1
FROM catalog_products p WHERE p.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('dog food'),('dry food'),('adult dog'),('chicken'),('everyday')) t(tag) ON TRUE
WHERE p.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables'
ON CONFLICT DO NOTHING;


-- 3) Whiskas Kitten Ocean Fish
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'FOOD',
  (SELECT id FROM brands WHERE name='Whiskas' LIMIT 1),
  'Whiskas',
  'Whiskas Kitten Dry Food – Ocean Fish',
  'For kittens (2–12 months). DHA supports brain development. Balanced vitamins and minerals.',
  'Tailored for growing kittens with DHA, calcium and high-quality protein to support healthy growth.',
  FALSE, '23091000', 'GST_5', 'Size', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Whiskas Kitten Dry Food – Ocean Fish');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Size', '1.1 kg', '1.1 kg', 'WH-KIT-FISH-1P1', 1, TRUE FROM catalog_products p WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish'
UNION ALL
SELECT p.id, 'Size', '3 kg',   '3 kg',   'WH-KIT-FISH-3KG',  2, TRUE FROM catalog_products p WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/kitten,petfood?lock=1202', 'Front', 1
FROM catalog_products p WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('cat food'),('kitten food'),('dry food'),('ocean fish'),('growth')) t(tag) ON TRUE
WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish'
ON CONFLICT DO NOTHING;


-- 4) Goofy Tails Rubber Bone Toy (Color variants)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'ACCESSORY',
  (SELECT id FROM brands WHERE name='Goofy Tails' LIMIT 1),
  'Goofy Tails',
  'Goofy Tails Squeaky Rubber Bone Toy',
  'Durable rubber squeaky toy for medium chewers. Helps reduce boredom. Great for fetch.',
  'Textured squeaky rubber bone toy. Suitable for supervised play. Choose color variants as available.',
  FALSE, '95030010', 'GST_18', 'Color', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Goofy Tails Squeaky Rubber Bone Toy');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Color', 'Yellow', 'Dumbbell', 'GT-BONE-YEL', 1, TRUE FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
UNION ALL
SELECT p.id, 'Color', 'Red',    'Classic',  'GT-BONE-RED', 2, TRUE FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
UNION ALL
SELECT p.id, 'Color', 'Blue',   'Classic',  'GT-BONE-BLU', 3, TRUE FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,toy?lock=2301', 'Front', 1
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,toy?lock=2302', 'In use', 2
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

-- add a "video" too (placeholder URL, use CDN later)
INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'VIDEO', 'https://example.com/videos/goofy-bone-demo.mp4', 'Demo video', 3
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('dog toy'),('rubber toy'),('squeaky'),('chew toy'),('fetch'),('toy bone')) t(tag) ON TRUE
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;


-- 5) Interactive Treat Ball (puzzle toy)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'ACCESSORY',
  (SELECT id FROM brands WHERE name='PetCare' LIMIT 1),
  'PetCare',
  'PetCare Interactive Treat Ball',
  'Puzzle toy that dispenses treats. Helps slow feeding and reduce boredom.',
  'Interactive treat dispensing ball for dogs. Adjust opening size to control treat release.',
  FALSE, '95030010', 'GST_18', NULL, TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='PetCare Interactive Treat Ball');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, NULL, NULL, 'Standard', 'PC-TREAT-BALL', 1, TRUE
FROM catalog_products p
WHERE p.title='PetCare Interactive Treat Ball'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,toy?lock=2304', 'Front', 1
FROM catalog_products p WHERE p.title='PetCare Interactive Treat Ball'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('dog toy'),('puzzle toy'),('treat dispenser'),('slow feeder')) t(tag) ON TRUE
WHERE p.title='PetCare Interactive Treat Ball'
ON CONFLICT DO NOTHING;


-- 6) Cat Litter (5kg/10kg)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'ACCESSORY',
  (SELECT id FROM brands WHERE name='PetCare' LIMIT 1),
  'PetCare',
  'PetCare Clumping Cat Litter',
  'Fast clumping litter with odor control. Low dust. Easy scoop.',
  'Clumping cat litter designed for quick absorption and odor control. Ideal for daily use for indoor cats.',
  FALSE, '25081010', 'GST_18', 'Size', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='PetCare Clumping Cat Litter');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Size', '5 kg',  '5 kg',  'PC-LITTER-5KG',  1, TRUE FROM catalog_products p WHERE p.title='PetCare Clumping Cat Litter'
UNION ALL
SELECT p.id, 'Size', '10 kg', '10 kg', 'PC-LITTER-10KG', 2, TRUE FROM catalog_products p WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/cat,litter?lock=6201', 'Front', 1
FROM catalog_products p WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('cat litter'),('clumping'),('odor control'),('low dust')) t(tag) ON TRUE
WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;


-- 7) Flea spray (200/500)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'MEDICINE',
  (SELECT id FROM brands WHERE name='Himalaya Pet' LIMIT 1),
  'Himalaya Pet',
  'Himalaya Tick & Flea Spray',
  'Helps control ticks and fleas. For external use. Avoid eyes and mouth.',
  'Tick & flea control spray for dogs. External use only. Follow label directions; consult vet if irritation occurs.',
  FALSE, '30049099', 'GST_12', 'Size', TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Himalaya Tick & Flea Spray');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, 'Size', '200 ml', '200 ml', 'HIM-FLEA-200', 1, TRUE FROM catalog_products p WHERE p.title='Himalaya Tick & Flea Spray'
UNION ALL
SELECT p.id, 'Size', '500 ml', '500 ml', 'HIM-FLEA-500', 2, TRUE FROM catalog_products p WHERE p.title='Himalaya Tick & Flea Spray'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,medicine?lock=5102', 'Front', 1
FROM catalog_products p WHERE p.title='Himalaya Tick & Flea Spray'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('tick control'),('flea control'),('pet hygiene'),('dog care')) t(tag) ON TRUE
WHERE p.title='Himalaya Tick & Flea Spray'
ON CONFLICT DO NOTHING;


-- 8) Bowl 900ml
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'ACCESSORY',
  (SELECT id FROM brands WHERE name='PetCare' LIMIT 1),
  'PetCare',
  'Stainless Steel Bowl 900ml',
  'Rust-resistant, easy to clean bowl for food and water. Stable base.',
  'Stainless steel bowl suitable for dogs and cats. Easy to wash and hygienic for everyday use.',
  FALSE, '73239390', 'GST_18', NULL, TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Stainless Steel Bowl 900ml');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, NULL, NULL, '900 ml', 'PC-BOWL-900', 1, TRUE
FROM catalog_products p
WHERE p.title='Stainless Steel Bowl 900ml'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/pet,bowl?lock=6204', 'Front', 1
FROM catalog_products p WHERE p.title='Stainless Steel Bowl 900ml'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('bowl'),('stainless steel'),('dog accessory'),('cat accessory')) t(tag) ON TRUE
WHERE p.title='Stainless Steel Bowl 900ml'
ON CONFLICT DO NOTHING;


-- 9) Grooming service (service is still a product)
INSERT INTO catalog_products (
  category, brand_id, brand_text, title, short_desc, description,
  prescription_required, hsn_code, tax_class, variant_theme, is_active
)
SELECT
  'SERVICE',
  (SELECT id FROM brands WHERE name='Groom & Glow' LIMIT 1),
  'Groom & Glow',
  'Groom & Glow – Bath + Dry (Dog)',
  'Bath and blow dry service for dogs. Appointment required.',
  'Includes bath, shampoo and blow dry. Add-on services available (nail trim, ear cleaning).',
  FALSE, NULL, 'GST_18', NULL, TRUE
WHERE NOT EXISTS (SELECT 1 FROM catalog_products WHERE title='Groom & Glow – Bath + Dry (Dog)');

INSERT INTO catalog_skus (product_id, variant_key, variant_value, pack_label, sku_code, sort_order, is_active)
SELECT p.id, NULL, NULL, 'Service', 'GG-BATH-DRY', 1, TRUE
FROM catalog_products p
WHERE p.title='Groom & Glow – Bath + Dry (Dog)'
ON CONFLICT DO NOTHING;

INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
SELECT p.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,grooming?lock=7102', 'Service', 1
FROM catalog_products p WHERE p.title='Groom & Glow – Bath + Dry (Dog)'
ON CONFLICT DO NOTHING;

INSERT INTO product_tags (product_id, tag)
SELECT p.id, t.tag
FROM catalog_products p
JOIN (VALUES ('grooming'),('dog grooming'),('service')) t(tag) ON TRUE
WHERE p.title='Groom & Glow – Bath + Dry (Dog)'
ON CONFLICT DO NOTHING;


-- =========================================================
-- STORE OFFERS (across multiple stores)
-- =========================================================

-- Ravi sells Royal Canin + Pedigree + Whiskas + Goofy Bone + Treat Ball
INSERT INTO store_offers (
  store_id, sku_id, is_active, price, mrp, discount_pct,
  stock_qty, reorder_level, shipping_fee, eta_text, eta_days_min, eta_days_max,
  returnable, warranty_months
)
SELECT
  ps.id,
  sku.id,
  TRUE,
  CASE
    WHEN pr.title='Royal Canin Medium Adult Dry Dog Food' AND sku.pack_label='2 kg' THEN 1299
    WHEN pr.title='Royal Canin Medium Adult Dry Dog Food' AND sku.pack_label='4 kg' THEN 2399
    WHEN pr.title='Royal Canin Medium Adult Dry Dog Food' AND sku.pack_label='10 kg' THEN 5499

    WHEN pr.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables' AND sku.pack_label='1.2 kg' THEN 349
    WHEN pr.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables' AND sku.pack_label='3 kg' THEN 899

    WHEN pr.title='Whiskas Kitten Dry Food – Ocean Fish' AND sku.pack_label='1.1 kg' THEN 489
    WHEN pr.title='Whiskas Kitten Dry Food – Ocean Fish' AND sku.pack_label='3 kg' THEN 1199

    WHEN pr.title='Goofy Tails Squeaky Rubber Bone Toy' AND sku.variant_value='Yellow' THEN 249
    WHEN pr.title='Goofy Tails Squeaky Rubber Bone Toy' THEN 239

    WHEN pr.title='PetCare Interactive Treat Ball' THEN 299
    ELSE 0
  END AS price,

  CASE
    WHEN pr.title='Goofy Tails Squeaky Rubber Bone Toy' AND sku.variant_value='Yellow' THEN 299
    WHEN pr.title='Goofy Tails Squeaky Rubber Bone Toy' THEN 279
    WHEN pr.title='PetCare Interactive Treat Ball' THEN 349
    WHEN pr.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables' AND sku.pack_label='3 kg' THEN 999
    ELSE NULL
  END AS mrp,

  CASE
    WHEN pr.title='Goofy Tails Squeaky Rubber Bone Toy' THEN 17
    WHEN pr.title='PetCare Interactive Treat Ball' THEN 14
    ELSE NULL
  END AS discount_pct,

  60, 15,
  0, 'Fast delivery', 1, 3,
  TRUE, NULL
FROM provider_stores ps
JOIN catalog_products pr ON pr.title IN (
  'Royal Canin Medium Adult Dry Dog Food',
  'Pedigree Adult Dry Dog Food – Chicken & Vegetables',
  'Whiskas Kitten Dry Food – Ocean Fish',
  'Goofy Tails Squeaky Rubber Bone Toy',
  'PetCare Interactive Treat Ball'
)
JOIN catalog_skus sku ON sku.product_id = pr.id
WHERE ps.display_name='Ravi Pet Mart'
ON CONFLICT (store_id, sku_id) DO NOTHING;

-- Asha sells bowl + litter + treat ball
INSERT INTO store_offers (
  store_id, sku_id, is_active, price, mrp, discount_pct,
  stock_qty, reorder_level, shipping_fee, eta_text, eta_days_min, eta_days_max,
  returnable, warranty_months
)
SELECT
  ps.id,
  sku.id,
  TRUE,
  CASE
    WHEN pr.title='Stainless Steel Bowl 900ml' THEN 159
    WHEN pr.title='PetCare Clumping Cat Litter' AND sku.pack_label='5 kg' THEN 399
    WHEN pr.title='PetCare Clumping Cat Litter' AND sku.pack_label='10 kg' THEN 749
    WHEN pr.title='PetCare Interactive Treat Ball' THEN 319
    ELSE 0
  END,
  CASE
    WHEN pr.title='Stainless Steel Bowl 900ml' THEN 199
    WHEN pr.title='PetCare Clumping Cat Litter' AND sku.pack_label='5 kg' THEN 499
    WHEN pr.title='PetCare Clumping Cat Litter' AND sku.pack_label='10 kg' THEN 899
    WHEN pr.title='PetCare Interactive Treat Ball' THEN 349
    ELSE NULL
  END,
  NULL,
  120, 20,
  0, 'Fast delivery', 1, 3,
  TRUE, NULL
FROM provider_stores ps
JOIN catalog_products pr ON pr.title IN ('Stainless Steel Bowl 900ml','PetCare Clumping Cat Litter','PetCare Interactive Treat Ball')
JOIN catalog_skus sku ON sku.product_id = pr.id
WHERE ps.display_name='Asha Pet Supplies'
ON CONFLICT (store_id, sku_id) DO NOTHING;

-- Pharma sells flea spray (and keep returnable false)
INSERT INTO store_offers (
  store_id, sku_id, is_active, price, mrp, discount_pct,
  stock_qty, reorder_level, shipping_fee, eta_text, eta_days_min, eta_days_max,
  returnable, warranty_months
)
SELECT
  ps.id,
  sku.id,
  TRUE,
  CASE WHEN sku.pack_label='200 ml' THEN 299 ELSE 599 END,
  CASE WHEN sku.pack_label='200 ml' THEN 349 ELSE 699 END,
  10,
  40, 10,
  0, 'Arriving in 2-3 days', 2, 3,
  FALSE, NULL
FROM provider_stores ps
JOIN catalog_products pr ON pr.title='Himalaya Tick & Flea Spray'
JOIN catalog_skus sku ON sku.product_id = pr.id
WHERE ps.display_name='Healthy Paws Pharma'
ON CONFLICT (store_id, sku_id) DO NOTHING;

-- Groom & Glow sells service
INSERT INTO store_offers (
  store_id, sku_id, is_active, price, mrp, discount_pct,
  stock_qty, reorder_level, shipping_fee, eta_text, eta_days_min, eta_days_max,
  returnable, warranty_months
)
SELECT
  ps.id,
  sku.id,
  TRUE,
  399,
  NULL,
  NULL,
  9999, 0,
  0, 'Book an appointment', 0, 0,
  FALSE, NULL
FROM provider_stores ps
JOIN catalog_products pr ON pr.title='Groom & Glow – Bath + Dry (Dog)'
JOIN catalog_skus sku ON sku.product_id = pr.id
WHERE ps.display_name='Groom & Glow'
ON CONFLICT (store_id, sku_id) DO NOTHING;


-- =========================================================
-- Promotions + targets
-- =========================================================
INSERT INTO promotions (title, subtitle, promo_type, discount_pct, discount_amount, min_qty, valid_from, valid_to, is_active)
VALUES
  ('Limited time deal', 'Save today on popular toys', 'DISCOUNT', 17, NULL, 1, now(), now() + interval '20 days', TRUE),
  ('₹100 coupon', 'On orders above ₹999', 'COUPON', NULL, 100, 1, now(), now() + interval '30 days', TRUE),
  ('Bank offer', '5% cashback with select cards', 'BANK', 5, NULL, 1, now(), now() + interval '15 days', TRUE)
ON CONFLICT DO NOTHING;

-- Attach deal to Goofy Bone + Treat Ball offers (Ravi store only)
INSERT INTO promotion_targets (promo_id, store_offer_id)
SELECT promo.id, so.id
FROM promotions promo
JOIN provider_stores ps ON ps.display_name='Ravi Pet Mart'
JOIN store_offers so ON so.store_id = ps.id
JOIN catalog_skus sku ON sku.id = so.sku_id
JOIN catalog_products pr ON pr.id = sku.product_id
WHERE promo.title='Limited time deal'
  AND pr.title IN ('Goofy Tails Squeaky Rubber Bone Toy','PetCare Interactive Treat Ball')
ON CONFLICT DO NOTHING;


-- =========================================================
-- Curated relations (product-level)
-- =========================================================
-- Bone toy -> Treat Ball (similar toys)
INSERT INTO item_relations (product_id, related_product_id, relation_type, weight)
SELECT p1.id, p2.id, 'SIMILAR', 95
FROM catalog_products p1, catalog_products p2
WHERE p1.title='Goofy Tails Squeaky Rubber Bone Toy'
  AND p2.title='PetCare Interactive Treat Ball'
ON CONFLICT DO NOTHING;

-- Bone toy -> bowl (FBT)
INSERT INTO item_relations (product_id, related_product_id, relation_type, weight)
SELECT p1.id, p2.id, 'FBT', 100
FROM catalog_products p1, catalog_products p2
WHERE p1.title='Goofy Tails Squeaky Rubber Bone Toy'
  AND p2.title='Stainless Steel Bowl 900ml'
ON CONFLICT DO NOTHING;

-- Treat Ball -> Pedigree (also like treats/food)
INSERT INTO item_relations (product_id, related_product_id, relation_type, weight)
SELECT p1.id, p2.id, 'ALSO_LIKE', 80
FROM catalog_products p1, catalog_products p2
WHERE p1.title='PetCare Interactive Treat Ball'
  AND p2.title='Pedigree Adult Dry Dog Food – Chicken & Vegetables'
ON CONFLICT DO NOTHING;

-- Whiskas kitten -> cat litter (FBT)
INSERT INTO item_relations (product_id, related_product_id, relation_type, weight)
SELECT p1.id, p2.id, 'FBT', 95
FROM catalog_products p1, catalog_products p2
WHERE p1.title='Whiskas Kitten Dry Food – Ocean Fish'
  AND p2.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;


-- =========================================================
-- Product reviews + media + helpful votes
-- =========================================================
-- Bone toy reviews
INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
SELECT p.id, s.id, 1, 5, 'My dog loves it',
       'Good grip, durable and squeaky. Keeps my pet engaged for 15-20 minutes.',
       TRUE
FROM catalog_products p
JOIN catalog_skus s ON s.product_id=p.id AND s.variant_value='Yellow'
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
SELECT p.id, s.id, 2, 4, 'Decent quality',
       'Nice toy. Squeaker is loud. Works well for fetch.',
       FALSE
FROM catalog_products p
JOIN catalog_skus s ON s.product_id=p.id AND s.variant_value='Red'
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

-- Review media (image + video)
INSERT INTO review_media (review_id, media_type, uri, sort_order)
SELECT r.id, 'IMAGE', 'https://loremflickr.com/900/900/dog,toy?lock=9001', 1
FROM item_reviews r
JOIN catalog_products p ON p.id = r.product_id
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy' AND r.user_id=1
ON CONFLICT DO NOTHING;

INSERT INTO review_media (review_id, media_type, uri, sort_order)
SELECT r.id, 'VIDEO', 'https://example.com/videos/reviews/bone-toy-usage.mp4', 2
FROM item_reviews r
JOIN catalog_products p ON p.id = r.product_id
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy' AND r.user_id=1
ON CONFLICT DO NOTHING;

-- Helpful votes
INSERT INTO review_votes (review_id, user_id, is_helpful)
SELECT r.id, 2, TRUE
FROM item_reviews r
JOIN catalog_products p ON p.id = r.product_id
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy' AND r.user_id=1
ON CONFLICT DO NOTHING;

INSERT INTO review_votes (review_id, user_id, is_helpful)
SELECT r.id, 1, TRUE
FROM item_reviews r
JOIN catalog_products p ON p.id = r.product_id
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy' AND r.user_id=2
ON CONFLICT DO NOTHING;

-- Whiskas review
INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
SELECT p.id, s.id, 1, 5, 'Great for kittens',
       'My kitten eats it happily and digestion is good.',
       TRUE
FROM catalog_products p
JOIN catalog_skus s ON s.product_id=p.id AND s.pack_label='1.1 kg'
WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish'
ON CONFLICT DO NOTHING;

-- Cat litter review
INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
SELECT p.id, s.id, 2, 4, 'Good clumping',
       'Clumps quickly and controls odor. Slight dust but manageable.',
       FALSE
FROM catalog_products p
JOIN catalog_skus s ON s.product_id=p.id AND s.pack_label='5 kg'
WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;


-- =========================================================
-- Store reviews (seller experience) + helpful votes
-- =========================================================
INSERT INTO store_reviews (store_id, user_id, rating, title, body)
SELECT ps.id, 1, 5, 'Great store', 'Fast delivery and good packaging.'
FROM provider_stores ps
WHERE ps.display_name='Ravi Pet Mart'
ON CONFLICT DO NOTHING;

INSERT INTO store_reviews (store_id, user_id, rating, title, body)
SELECT ps.id, 2, 4, 'Reliable', 'Items as described. Support was responsive.'
FROM provider_stores ps
WHERE ps.display_name='Asha Pet Supplies'
ON CONFLICT DO NOTHING;

INSERT INTO store_review_votes (review_id, user_id, is_helpful)
SELECT r.id, 2, TRUE
FROM store_reviews r
JOIN provider_stores ps ON ps.id = r.store_id
WHERE ps.display_name='Ravi Pet Mart' AND r.user_id=1
ON CONFLICT DO NOTHING;


-- =========================================================
-- Q/A
-- =========================================================
INSERT INTO item_questions (product_id, user_id, question)
SELECT p.id, 2, 'Is this toy suitable for aggressive chewers?'
FROM catalog_products p
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO item_answers (question_id, user_id, answer)
SELECT q.id, 1, 'Suitable for medium chewers. For aggressive chewers, supervise and replace if damaged.'
FROM item_questions q
JOIN catalog_products p ON p.id = q.product_id
WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy'
ON CONFLICT DO NOTHING;

INSERT INTO item_questions (product_id, user_id, question)
SELECT p.id, 1, 'Does this cat litter control odor well?'
FROM catalog_products p
WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;

INSERT INTO item_answers (question_id, user_id, answer)
SELECT q.id, 2, 'Yes, odor control is good if scooped daily and litter box is ventilated.'
FROM item_questions q
JOIN catalog_products p ON p.id = q.product_id
WHERE p.title='PetCare Clumping Cat Litter'
ON CONFLICT DO NOTHING;


-- =========================================================
-- Wishlists
-- =========================================================
INSERT INTO wishlists (user_id)
SELECT u.id FROM users u WHERE u.id IN (1,2)
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO wishlist_items (wishlist_id, product_id)
SELECT w.id, p.id
FROM wishlists w
JOIN catalog_products p ON p.title='Goofy Tails Squeaky Rubber Bone Toy'
WHERE w.user_id=1
ON CONFLICT DO NOTHING;


-- =========================================================
-- Carts + cart items (so API works immediately)
-- =========================================================
INSERT INTO carts (parent_user_id, address_id)
SELECT u.id,
       (SELECT a.id FROM user_addresses a WHERE a.user_id=u.id AND a.is_default=TRUE LIMIT 1)
FROM users u
WHERE u.id IN (1,2)
ON CONFLICT (parent_user_id) DO NOTHING;

-- Put one item in cart for user 1 (Goofy bone Yellow from Ravi)
INSERT INTO cart_items (cart_id, store_offer_id, qty)
SELECT
  c.id,
  so.id,
  1
FROM carts c
JOIN provider_stores ps ON ps.display_name='Ravi Pet Mart'
JOIN store_offers so ON so.store_id = ps.id
JOIN catalog_skus sku ON sku.id = so.sku_id
JOIN catalog_products p ON p.id = sku.product_id
WHERE c.parent_user_id=1
  AND p.title='Goofy Tails Squeaky Rubber Bone Toy'
  AND sku.variant_value='Yellow'
ON CONFLICT DO NOTHING;


-- =========================================================
-- Events (signals for trending / bought-in-month)
-- =========================================================
-- simulate recent views & adds
INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 1, p.id, 'VIEW', now() - interval '1 day', '{}'::jsonb
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy';

INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 2, p.id, 'VIEW', now() - interval '2 days', '{}'::jsonb
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy';

INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 1, p.id, 'ADD_TO_CART', now() - interval '1 day', '{"qty":1}'::jsonb
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy';

-- simulate purchases in last 30 days
INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 1, p.id, 'PURCHASE', now() - interval '10 days', '{"qty":1}'::jsonb
FROM catalog_products p WHERE p.title='Goofy Tails Squeaky Rubber Bone Toy';

INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 2, p.id, 'PURCHASE', now() - interval '18 days', '{"qty":2}'::jsonb
FROM catalog_products p WHERE p.title='Whiskas Kitten Dry Food – Ocean Fish';

INSERT INTO user_item_events (user_id, product_id, event_type, created_at, meta)
SELECT 1, p.id, 'PURCHASE', now() - interval '6 days', '{"qty":1}'::jsonb
FROM catalog_products p WHERE p.title='PetCare Clumping Cat Litter';
