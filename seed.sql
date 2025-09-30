-- seed.sql (no orgs)

-- Users (Asha has parent+vet; active role set to parent)
INSERT INTO users (id, phone, email, name, active_role) VALUES
  (1, '09840185469', 'asha@example.com',         'Asha Rao',       'parent'),
  (2, '9876543210',  'krish@example.com',        'Krish Malhotra', NULL),
  (3, '9123456780',  'meera.shah@pawsclinic.com','Dr. Meera Shah', 'vet')
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
INSERT INTO vet_locations (user_id, name, line1, line2, city, lat, lng, hours, is_primary) VALUES
  (1, 'Paws Care – Adyar', '42, 2nd Main Rd', 'LB Rd', 'Chennai', 13.0001, 80.2663, 'Mon–Sat 09:00–18:00', TRUE),
  (3, 'Paws Clinic – Vastrapur', '8 Lake View', NULL, 'Ahmedabad', 23.0356, 72.5293, 'Mon–Sat 10:00–19:00', TRUE)
ON CONFLICT DO NOTHING;


-- Sync sequences to current max IDs after seeding
SELECT setval(pg_get_serial_sequence('users','id'),      COALESCE((SELECT MAX(id) FROM users),0)+1, false);
SELECT setval(pg_get_serial_sequence('user_roles','id'), COALESCE((SELECT MAX(id) FROM user_roles),0)+1, false);
SELECT setval(pg_get_serial_sequence('pets','id'),       COALESCE((SELECT MAX(id) FROM pets),0)+1, false);
SELECT setval(pg_get_serial_sequence('pet_reports','id'),COALESCE((SELECT MAX(id) FROM pet_reports),0)+1, false);
SELECT setval(pg_get_serial_sequence('vaccinations','id'),COALESCE((SELECT MAX(id) FROM vaccinations),0)+1, false);
SELECT setval(pg_get_serial_sequence('vet_locations','id'), COALESCE((SELECT MAX(id) FROM vet_locations),0)+1, false);

-- === Seed data for demoing Vet Appointments ===

BEGIN;

-- Minimal: rely on your existing users, user_roles, pets, vet_profiles, vet_locations.
-- Add schedule templates, vaccine catalog, slots, appointments in varied states, prescriptions, invoices.

-- Schedule templates
INSERT INTO vet_schedule_templates (vet_id, location_id, mode, slot_minutes, min_gap_minutes, workdays, day_start, day_end, breaks, horizon_days)
VALUES
  (1, 1, 'in_person', 15, 5, '{1,2,3,4,5,6}', '09:00', '13:00', '[{"start":"13:00","end":"16:00","label":"lunch"}]', 14),
  (1, 1, 'video',     15, 0, '{1,2,3,4,5,6}', '19:00', '21:00', '[]', 14),
  (3, 2, 'in_person', 15, 5, '{1,2,3,4,5,6}', '10:00', '13:00', '[]', 14);

-- Vaccine catalog
INSERT INTO vaccine_catalog (species, code, name, brand, default_schedule_json) VALUES
 ('dog','ARV','Anti-rabies','Nobivac','{"initial_weeks":12,"annual_every_weeks":52}'),
 ('dog','DHPPiL','DHPPiL','Nobivac','{"initial_weeks":8,"booster_weeks":[12,16],"annual_every_weeks":52}'),
 ('cat','FVRCP','FVRCP','Purevax','{"initial_weeks":8,"booster_weeks":[12,16],"annual_every_weeks":52}')
ON CONFLICT DO NOTHING;

-- Enable vaccines at clinics
INSERT INTO clinic_vaccine_enabled (vet_id, vaccine_id, enabled, stock)
SELECT 1, id, TRUE, 10 FROM vaccine_catalog;
INSERT INTO clinic_vaccine_enabled (vet_id, vaccine_id, enabled, stock)
SELECT 3, id, TRUE, 5 FROM vaccine_catalog;

-- Materialize a few slots (for demo; real app should generate programmatically)
-- Today and tomorrow around local time windows
INSERT INTO slots (vet_id, location_id, mode, start_ts, end_ts, status) VALUES
 (1, 1, 'in_person', now()::timestamptz + interval '1 hour',  now()::timestamptz + interval '1 hour 15 minutes', 'BOOKED'),
 (1, 1, 'in_person', now()::timestamptz + interval '2 hours', now()::timestamptz + interval '2 hours 15 minutes', 'OPEN'),
 (1, 1, 'video',     date_trunc('day', now()) + interval '19 hour', date_trunc('day', now()) + interval '19 hour 15 minutes', 'OPEN'),
 (3, 2, 'in_person', now()::timestamptz + interval '30 minutes', now()::timestamptz + interval '45 minutes', 'BOOKED');

-- Appointments with varied states
-- Assume users: parent=2 (Krish), parent=1 (Asha as parent), vets: 1 (Asha), 3 (Meera); pets seeded already.
-- 1) Confirmed upcoming
INSERT INTO appointments (slot_id, vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  1, 1, 1, 2, 1, 'in_person',
  (SELECT start_ts FROM slots WHERE id=1), (SELECT end_ts FROM slots WHERE id=1),
  'CONFIRMED', NULL, 'Skin rash follow-up'
);

-- 2) Arrived (waiting)
INSERT INTO appointments (slot_id, vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  4, 3, 2, 2, 1, 'in_person',
  (SELECT start_ts FROM slots WHERE id=4), (SELECT end_ts FROM slots WHERE id=4),
  'CONFIRMED', 'ARRIVED', 'General check-up'
);

-- 3) In consultation
INSERT INTO appointments (vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  1, 1, 1, 1, 'in_person',
  now()::timestamptz - interval '10 minutes', now()::timestamptz + interval '5 minutes',
  'CONFIRMED', 'IN_CONSULTATION', 'Limping - likely sprain'
);

-- 4) Completed + Rx + Invoice
INSERT INTO appointments (vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  1, 1, 1, 1, 'video',
  now()::timestamptz - interval '2 days', now()::timestamptz - interval '2 days' + interval '15 minutes',
  'CONFIRMED', 'CONSULTATION_COMPLETE', 'Follow-up video'
);

INSERT INTO prescriptions (appointment_id, diagnosis, notes) VALUES
 ((SELECT max(id) FROM appointments), 'Allergic dermatitis', 'Hydration + avoid triggers');

INSERT INTO prescription_items (prescription_id, drug_name, dose, frequency, before_after_food) VALUES
 ((SELECT id FROM prescriptions ORDER BY id DESC LIMIT 1), 'Cetirizine 10mg', '1/2 tab', 'OD', 'after food');

-- Invoice for the completed appointment
INSERT INTO invoices (appointment_id, vet_id, location_id, invoice_no, bill_to_parent_id, clinic_legal_name, clinic_address, gstin, subtotal, tax_cgst, tax_sgst, tax_igst, total, status)
VALUES (
  (SELECT max(id) FROM appointments), 1, 1,
  'INV-ADY-202509-0001',
  1,
  (SELECT legal_name FROM vet_profiles WHERE user_id=1),
  (SELECT COALESCE(line1,'') || E'\n' || COALESCE(line2,'') || E'\n' || COALESCE(city,'') FROM vet_locations WHERE id=1),
  (SELECT gstin FROM vet_profiles WHERE user_id=1),
  1000, 90, 90, 0, 1180, 'paid'
);

INSERT INTO invoice_items (invoice_id, description, qty, unit_price, amount, tax_rate)
VALUES
 ((SELECT id FROM invoices ORDER BY id DESC LIMIT 1), 'Video Consultation (15 min)', 1, 1000, 1000, 18);

-- 5) Cancelled by parent
INSERT INTO appointments (vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  1, 1, 2, 1, 'in_person',
  now()::timestamptz + interval '1 day', now()::timestamptz + interval '1 day 15 minutes',
  'CANCELLED_BY_PARENT', NULL, 'Schedule conflict'
);

-- 6) Reschedule proposed by vet (pending)
INSERT INTO appointments (vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES (
  1, 1, 2, 1, 'in_person',
  now()::timestamptz + interval '2 days', now()::timestamptz + interval '2 days 15 minutes',
  'RESCHEDULE_PROPOSED_BY_VET', NULL, 'Doctor travel delay'
);

COMMIT;

-- Sync sequences (useful in dev)
SELECT setval(pg_get_serial_sequence('vet_schedule_templates','id'), COALESCE((SELECT MAX(id) FROM vet_schedule_templates),0)+1, false);
SELECT setval(pg_get_serial_sequence('slots','id'), COALESCE((SELECT MAX(id) FROM slots),0)+1, false);
SELECT setval(pg_get_serial_sequence('appointments','id'), COALESCE((SELECT MAX(id) FROM appointments),0)+1, false);
SELECT setval(pg_get_serial_sequence('appointment_audit','id'), COALESCE((SELECT MAX(id) FROM appointment_audit),0)+1, false);
SELECT setval(pg_get_serial_sequence('prescriptions','id'), COALESCE((SELECT MAX(id) FROM prescriptions),0)+1, false);
SELECT setval(pg_get_serial_sequence('prescription_items','id'), COALESCE((SELECT MAX(id) FROM prescription_items),0)+1, false);
SELECT setval(pg_get_serial_sequence('vaccine_catalog','id'), COALESCE((SELECT MAX(id) FROM vaccine_catalog),0)+1, false);
SELECT setval(pg_get_serial_sequence('clinic_vaccine_enabled','id'), COALESCE((SELECT MAX(id) FROM clinic_vaccine_enabled),0)+1, false);
SELECT setval(pg_get_serial_sequence('pet_vaccination_plan','id'), COALESCE((SELECT MAX(id) FROM pet_vaccination_plan),0)+1, false);
SELECT setval(pg_get_serial_sequence('pet_vaccinations_given','id'), COALESCE((SELECT MAX(id) FROM pet_vaccinations_given),0)+1, false);
SELECT setval(pg_get_serial_sequence('invoices','id'), COALESCE((SELECT MAX(id) FROM invoices),0)+1, false);
SELECT setval(pg_get_serial_sequence('invoice_items','id'), COALESCE((SELECT MAX(id) FROM invoice_items),0)+1, false);

BEGIN;
INSERT INTO vaccine_catalog (species, code, name, brand, default_schedule_json) VALUES
 ('dog','ARV','Anti-rabies','Nobivac','{"initial_weeks":12,"annual_every_weeks":52}')
ON CONFLICT DO NOTHING;
INSERT INTO clinic_vaccine_enabled (vet_id, vaccine_id, enabled, stock)
SELECT 1, id, TRUE, 10 FROM vaccine_catalog WHERE code='ARV' ON CONFLICT DO NOTHING;
INSERT INTO vet_schedule_templates
(vet_id, location_id, mode, slot_minutes, min_gap_minutes, workdays, day_start, day_end, breaks, horizon_days)
VALUES (1,1,'in_person',15,5,'{1,2,3,4,5,6}','09:00','12:00','[{"start":"12:00","end":"16:00","label":"break"}]',7)
ON CONFLICT DO NOTHING;
INSERT INTO slots (vet_id, location_id, mode, start_ts, end_ts, status) VALUES
(1,1,'in_person', now() + interval '1 hour', now() + interval '1 hour 15 minutes','BOOKED'),
(1,1,'in_person', now() + interval '2 hour', now() + interval '2 hour 15 minutes','OPEN');
INSERT INTO appointments (slot_id, vet_id, location_id, parent_id, pet_id, mode, start_ts, end_ts, calendar_state, visit_state, notes)
VALUES ((SELECT id FROM slots WHERE status='BOOKED' LIMIT 1),1,1,2,1,'in_person',
        (SELECT start_ts FROM slots WHERE status='BOOKED' LIMIT 1),
        (SELECT end_ts FROM slots WHERE status='BOOKED' LIMIT 1),
        'CONFIRMED', NULL, 'Demo appointment');
COMMIT;