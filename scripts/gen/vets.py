# scripts/gen/vets.py
from __future__ import annotations

import random, json
from typing import List, Dict

def _week_24h_rules():
    # ✅ user asked 24h windows, every day
    day = [{"start": "00:00", "end": "23:59"}]
    return {"mon": day, "tue": day, "wed": day, "thu": day, "fri": day, "sat": day, "sun": day}

def seed_vets(conn, vet_user_ids: List[int], cfg) -> Dict[str, List[int]]:
    rng = random.Random(cfg.rng_seed + 700)

    with conn.cursor() as cur:
        # roles
        cur.executemany(
            "INSERT INTO user_roles (user_id, role) VALUES (%s,'vet') ON CONFLICT DO NOTHING",
            [(vid,) for vid in vet_user_ids],
        )

        # profiles
        prof_rows = []
        for vid in vet_user_ids:
            prof_rows.append((
                vid,
                f"Paws & Co {vid}",
                f"Dr. Vet {vid}",
                f"accounts{vid}@paws.example.com",
                None,
                f"{vid} Clinic Street\nVizag 5300{vid%10:02d}",
                None, None,
                rng.choice(["BVSc & AH", "BVSc, MVSc"]),
                f"LIC-{vid:05d}",
                int(rng.randint(1, 15)),
                json.dumps(rng.sample(["dermatology","surgery","dentistry","general","nutrition"], k=2)),
                True, True,
                int(rng.choice([400,500,600,700,800])),
                int(rng.choice([300,400,500,600])),
                int(getattr(cfg, "slot_minutes", 2)),
            ))

        cur.executemany(
            """
            INSERT INTO vet_profiles (
              user_id, legal_name, display_name, business_email, billing_email, billing_address,
              gstin, pan, qualifications, license_no, experience_years, specialties,
              visit_in_clinic, visit_video, fee_in_clinic, fee_video, slot_minutes
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            prof_rows,
        )

        # locations (>=1 per vet)
        location_ids: List[int] = []
        locs_per_vet = max(1, int(getattr(cfg, "locations_per_vet", 1)))

        for vid in vet_user_ids:
            for k in range(locs_per_vet):
                cur.execute(
                    """
                    INSERT INTO vet_locations (user_id, name, line1, line2, city, lat, lng, hours, is_primary)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        vid,
                        f"Paws Clinic {vid}-{k+1}",
                        f"Dwaraka Nagar {vid%50}",
                        "Near Park",
                        "Vizag",
                        17.70 + rng.random()/10,
                        83.30 + rng.random()/10,
                        "24x7",
                        (k == 0),
                    ),
                )
                location_ids.append(int(cur.fetchone()[0]))

        # slot_settings (in_person + video per location)
        slot_setting_ids: List[int] = []
        rules = _week_24h_rules()
        slot_min = max(2, int(getattr(cfg, "slot_minutes", 2)))

        # map vet -> its location ids
        cur.execute("SELECT user_id, id FROM vet_locations WHERE user_id = ANY(%s) ORDER BY id", (vet_user_ids,))
        vet_to_locs: Dict[int, List[int]] = {}
        for v, lid in cur.fetchall():
            vet_to_locs.setdefault(int(v), []).append(int(lid))

        for vid in vet_user_ids:
            for loc_id in vet_to_locs.get(vid, []):
                for ctype in ("in_person", "video"):
                    cur.execute(
                        """
                        INSERT INTO slot_settings (
                          user_id, location_id, consultation_type,
                          slot_minutes, gap_minutes, per_slot_capacity,
                          lead_time_minutes, booking_window_days, visible_to_parents,
                          week_rules, blackout_dates, effective_from, effective_to
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,NULL,NULL)
                        RETURNING id
                        """,
                        (
                            vid, loc_id, ctype,
                            slot_min, 0, 1,
                            0, 30, True,
                            json.dumps(rules),
                            json.dumps([]),
                        ),
                    )
                    slot_setting_ids.append(int(cur.fetchone()[0]))

        # light overrides
        cur.execute("SELECT id FROM slot_settings ORDER BY id")
        ss = [int(r[0]) for r in cur.fetchall()]
        for sid in rng.sample(ss, k=min(100, len(ss))):
            cur.execute(
                """
                INSERT INTO slot_overrides (slot_setting_id, date, payload)
                VALUES (%s, CURRENT_DATE + (random()*10)::int, %s::jsonb)
                ON CONFLICT (slot_setting_id, date) DO NOTHING
                """,
                (sid, json.dumps({"block_windows":[{"start":"03:00","end":"04:00"}]})),
            )

    return {"vet_ids": vet_user_ids, "location_ids": location_ids, "slot_setting_ids": slot_setting_ids}
