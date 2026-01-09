# scripts/gen/stores.py
from __future__ import annotations
import random
from typing import List

CITIES = [("Vizag","AP","530001"),("Hyderabad","TS","500081"),("Bengaluru","KA","560001"),("Chennai","TN","600020")]
STORE_NAMES = ["Pet Mart","Healthy Paws","Paws & Co","PetCare Store","Happy Tails","Purrfect Supplies","Doggo Depot","Kitty Korner"]

def seed_stores(conn, owner_ids: List[int], cfg) -> List[int]:
    rng = random.Random(cfg.rng_seed + 11)
    n = int(cfg.num_stores)

    rows = []
    for i in range(n):
        owner = owner_ids[i % len(owner_ids)]
        role = rng.choice(["vendor","pharmacist"])
        city, state, pin = rng.choice(CITIES)
        display = f"{rng.choice(STORE_NAMES)} {i+1}"
        rows.append((
            owner, role, display,
            f"+91{9000000000 + i}", f"store{i+1}@example.com",
            None, f"Store {i+1} for dogs/cats",
            "ACTIVE",
            f"Area {i%50}", f"Street {i%100}",
            city, state, pin,
            (f"LIC-{i+1}" if role=="pharmacist" else None),
            None
        ))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO provider_stores
              (owner_user_id, role, display_name, phone, email, logo_uri, about,
               status, address_line1, address_line2, city, state, pincode,
               license_no, license_valid_till)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (owner_user_id, role) DO NOTHING
            """,
            rows,
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM provider_stores ORDER BY id ASC")
        return [int(r[0]) for r in cur.fetchall()]
