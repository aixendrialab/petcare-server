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
    Ensure we have *at least* cfg.num_users users in the DB (including SPECIAL_USERS).
    Returns ALL user ids (sorted).
    """
    rng = random.Random(cfg.rng_seed + 10)

    # 1) Insert special users (idempotent)
    ensure_special_users(conn)

    # 2) Load existing users
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id")
        existing_ids = [int(r[0]) for r in cur.fetchall()]

    target = int(getattr(cfg, "num_users", 0) or 0)
    if target <= 0:
        return existing_ids

    needed = max(0, target - len(existing_ids))
    if needed:
        seed_more_users(conn, cfg, needed, rng=rng)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id")
        return [int(r[0]) for r in cur.fetchall()]


def seed_more_users(conn, cfg, count: int, rng: random.Random | None = None) -> List[int]:
    """
    Inserts `count` additional generic users (active_role='parent' by default).
    Returns their ids.
    """
    rng = rng or random.Random(cfg.rng_seed + 11)
    rows = []
    # Generate deterministic-ish phone ranges to avoid collisions
    base = int(getattr(cfg, "random_phone_base", 910000000000))
    # Offset by current max id to keep uniqueness stable
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id),0) FROM users")
        max_id = int(cur.fetchone()[0] or 0)

    for i in range(count):
        n = max_id + i + 1
        phone = f"+91{(base + n) % 10000000000:010d}"
        email = f"user{n}@example.com"
        name = f"User {n}"
        rows.append((phone, email, name, "parent"))

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO users (phone, email, name, active_role) VALUES (%s,%s,%s,%s)",
            rows,
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users ORDER BY id DESC LIMIT %s", (count,))
        ids = [int(r[0]) for r in cur.fetchall()]
    return list(reversed(ids))

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
