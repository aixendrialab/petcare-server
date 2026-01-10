# scripts/gen/vaccines.py
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List, Dict, Tuple

DOG_VAX = [("DHPP","core"), ("RABIES","core"), ("LEPTO","optional"), ("KC","optional")]
CAT_VAX = [("FVRCP","core"), ("RABIES","core"), ("FELV","optional")]

def seed_vaccine_catalog(conn) -> None:
    rows = []
    for code, vtype in DOG_VAX:
        rows.append((code, "dog", f"{code} vaccine", vtype, f"{code} for dogs", True))
    for code, vtype in CAT_VAX:
        rows.append((code, "cat", f"{code} vaccine", vtype, f"{code} for cats", True))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO vaccine_catalog (code, species, name, vaccine_type, description, is_active)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (code, species) DO NOTHING
            """,
            rows,
        )

def seed_pet_vaccines(conn, pet_ids: List[int], vet_user_ids: List[int], cfg) -> Dict[str, int]:
    rng = random.Random(cfg.rng_seed + 750)

    plan_cnt = 0
    record_cnt = 0
    item_cnt = 0
    completed_items = 0

    with conn.cursor() as cur:
        cur.execute("SELECT id, code, species FROM vaccine_catalog")
        vmap = {(r[1], r[2]): int(r[0]) for r in cur.fetchall()}

        cur.execute("SELECT id, species FROM pets WHERE id = ANY(%s)", (pet_ids,))
        pets = [(int(r[0]), r[1]) for r in cur.fetchall()]

        for pet_id, species in pets:
            # create plan
            if rng.random() <= float(cfg.pct_pets_with_vaccine_plan):
                cur.execute(
                    """
                    INSERT INTO pet_vaccine_plan (pet_id, status, notes)
                    VALUES (%s,'SUGGESTED','Auto-seeded')
                    ON CONFLICT (pet_id) DO UPDATE SET generated_at=now()
                    RETURNING id
                    """,
                    (pet_id,),
                )
                plan_id = int(cur.fetchone()[0])
                plan_cnt += 1

                picks = DOG_VAX if species == "dog" else CAT_VAX
                base = date.today()

                # create 3 plan items
                created_plan_item_ids: List[int] = []
                for dose_no, (code, _vtype) in enumerate(picks[:3], start=1):
                    vid = vmap.get((code, species))
                    if not vid:
                        continue
                    home_window = int(getattr(cfg, 'vaccine_home_window_days', 30))
                    # Guarantee first item visible on parent home ([-7 .. +home_window])
                    if dose_no == 1:
                        due = base + timedelta(days=rng.randint(-7, home_window))
                    else:
                        due = base + timedelta(days=rng.randint(-30, 180))
                    status = "DUE" if due <= date.today() else "UPCOMING"
                    cur.execute(
                        """
                        INSERT INTO pet_vaccine_plan_item (plan_id, vaccine_id, dose_no, due_on, status)
                        VALUES (%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (plan_id, vid, dose_no, due, status),
                    )
                    created_plan_item_ids.append(int(cur.fetchone()[0]))
                    item_cnt += 1

                # Force some completed plan items + create vaccination_record with vet_id
                pct_done = float(getattr(cfg, "pct_plan_items_completed", 0.35))
                for plan_item_id in created_plan_item_ids:
                    if rng.random() > pct_done:
                        continue
                    # load vaccine_id from plan_item
                    cur.execute("SELECT vaccine_id, due_on FROM pet_vaccine_plan_item WHERE id=%s", (plan_item_id,))
                    vaccine_id, due_on = cur.fetchone()
                    vaccine_id = int(vaccine_id)
                    given = (due_on - timedelta(days=rng.randint(0, 7))) if due_on else (date.today() - timedelta(days=10))
                    next_due = date.today() + timedelta(days=rng.randint(30, 180))

                    vet_id = rng.choice(vet_user_ids) if vet_user_ids else None

                    cur.execute(
                        """
                        INSERT INTO vaccination_record (pet_id, vaccine_id, vaccine_type, last_given, next_due, notes, vet_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (pet_id, vaccine_id, "core", given, next_due, "Auto record", vet_id),
                    )
                    rec_id = int(cur.fetchone()[0])
                    record_cnt += 1

                    cur.execute(
                        """
                        UPDATE pet_vaccine_plan_item
                        SET status='COMPLETED', completed_on=%s, completed_record_id=%s
                        WHERE id=%s
                        """,
                        (given, rec_id, plan_item_id),
                    )
                    completed_items += 1

            # extra records even without plan
            if rng.random() <= float(cfg.pct_pets_with_vaccine_records):
                picks = DOG_VAX if species == "dog" else CAT_VAX
                code, _ = rng.choice(picks)
                vid = vmap.get((code, species))
                if vid:
                    last_given = date.today() - timedelta(days=rng.randint(30, 500))
                    next_due = date.today() + timedelta(days=rng.randint(10, 180))
                    vet_id = rng.choice(vet_user_ids) if vet_user_ids else None
                    cur.execute(
                        """
                        INSERT INTO vaccination_record (pet_id, vaccine_id, vaccine_type, last_given, next_due, notes, vet_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (pet_id, int(vid), "core", last_given, next_due, "Auto record", vet_id),
                    )
                    record_cnt += 1

    return {"plans": plan_cnt, "plan_items": item_cnt, "records": record_cnt, "completed_items": completed_items}
