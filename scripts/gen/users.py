# scripts/gen/users.py
from __future__ import annotations

import random
from typing import List, Tuple, Dict


SPECIAL_USERS = [
    # phone, name, email, roles
    ("+919900000001", "Asha Rao",      "asha@example.com",      ["parent", "vet", "vendor"]),
    ("+919900000002", "Vikram Singh",  "vikram@example.com",    ["parent"]),
    ("+919900000003", "Dr Meera Shah", "meera@pawsclinic.com",  ["vet"]),
    ("+919900000004", "Ravi Vendor",   "ravi@vendor.com",       ["vendor"]),
    ("+919900000005", "Sita Pharma",   "sita@pharma.com",       ["pharmacist"]),
    ("+919900000006", "Kiran Groom",   "kiran@groom.com",       ["vendor"]),
]

def ensure_special_users(conn) -> dict:
    """
    Idempotently upserts SPECIAL_USERS into:
      - users
      - user_roles

    Returns:
      {
        "all": [ids...],
        "by_role": {"parent":[...], "vet":[...], "vendor":[...], ...}
      }
    """
    by_role: Dict[str, List[int]] = {}
    all_ids: List[int] = []

    with conn.cursor() as cur:
        for phone, name, email, roles in SPECIAL_USERS:
            active_role = roles[0] if roles else "parent"

            # Upsert user by phone
            cur.execute(
                """
                INSERT INTO users (phone, email, name, active_role)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (phone) DO UPDATE SET
                  email = EXCLUDED.email,
                  name = EXCLUDED.name,
                  active_role = EXCLUDED.active_role
                RETURNING id
                """,
                (phone, email, name, active_role),
            )
            uid = int(cur.fetchone()[0])
            all_ids.append(uid)

            # Ensure roles
            for r in roles:
                cur.execute(
                    "INSERT INTO user_roles (user_id, role) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (uid, r),
                )
                by_role.setdefault(r, []).append(uid)

    return {"all": all_ids, "by_role": by_role}


def seed_users(conn, cfg) -> List[int]:
    """
    Creates cfg.num_users users.
    Always inserts SPECIAL_USERS first (id stable? not required).
    Returns list of user ids.
    """
    rng = random.Random(cfg.rng_seed + 10)

    # 1) Insert special users (idempotent)
    ensure_special_users(conn)

    # 2) Count how many users exist after specials
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id")
        existing_ids = [int(r[0]) for r in cur.fetchall()]

    need = max(0, int(cfg.num_users) - len(existing_ids))
    if need <= 0:
        return existing_ids[: int(cfg.num_users)]

    # 3) Insert generated users
    # Keep phone unique and human-ish names
    first_names = ["User", "Arjun", "Neha", "Rahul", "Priya", "Kiran", "Aditi", "Rohan", "Meera", "Vikram"]
    last_names = ["Singh", "Rao", "Shah", "Patel", "Nair", "Iyer", "Khan", "Das", "Gupta", "Reddy"]

    rows: List[Tuple[str, str, str, str]] = []
    # phone range for generated: +9191xxxxxxxxxx
    base = 910000000000
    used_phones = set(u[0] for u in SPECIAL_USERS)

    i = 0
    while len(rows) < need:
        phone = f"+91{base + i}"
        i += 1
        if phone in used_phones:
            continue
        used_phones.add(phone)
        name = f"{rng.choice(first_names)} {rng.choice(last_names)}"
        email = f"user{phone[-7:]}@example.com"
        # active_role can be NULL; but for your app flows parent helps
        rows.append((phone, email, name, "parent"))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO users (phone, email, name, active_role)
            VALUES (%s,%s,%s,%s)
            """,
            rows,
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id")
        return [int(r[0]) for r in cur.fetchall()][: int(cfg.num_users)]


def ensure_roles(conn, user_ids: List[int], role: str, pct: float, seed: int) -> List[int]:
    rng = random.Random(seed)
    picked = []
    for uid in user_ids:
        if rng.random() < pct:
            picked.append(uid)

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO user_roles (user_id, role) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            [(uid, role) for uid in picked],
        )
    return picked
