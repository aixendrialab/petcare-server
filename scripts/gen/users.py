# scripts/gen/users.py
from __future__ import annotations
import random
from typing import List

ROLES = ["parent", "vet", "vendor", "pharmacist", "hostel", "nutritionist", "walker"]

FIRST = ["Asha","Krish","Meera","Ravi","Sita","Kiran","Anil","Pooja","Rahul","Divya","Vikram","Neha"]
LAST  = ["Rao","Shah","Malhotra","Kumar","Reddy","Singh","Patel","Iyer","Das","Gupta"]

def seed_users(conn, cfg) -> List[int]:
    seed_more_users(conn, cfg, int(cfg.num_users))
    return _load_user_ids(conn)

def seed_more_users(conn, cfg, count: int) -> None:
    if count <= 0:
        return
    rng = random.Random(cfg.rng_seed)
    rows = []
    # create unique phones/emails
    base = rng.randint(9000000000, 9999999999)
    for i in range(count):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        phone = f"+91{base + i}"
        email = f"user{base+i}@example.com"
        active_role = rng.choice(["parent", "vendor", "pharmacist"])
        rows.append((phone, email, name, active_role))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO users (phone, email, name, active_role)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (phone) DO NOTHING
            """,
            rows,
        )

def _load_user_ids(conn) -> List[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id ASC")
        return [int(r[0]) for r in cur.fetchall()]
