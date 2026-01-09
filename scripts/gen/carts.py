# scripts/gen/carts.py
from __future__ import annotations

import random
from typing import List
from scripts.gen.specials import SPECIAL_USERS


def _special_parent_phones() -> List[str]:
    out = []
    for phone, _name, _email, roles in SPECIAL_USERS:
        if "parent" in roles:
            out.append(phone)
    return out


def _resolve_user_ids_by_phone(conn, phones: List[str]) -> List[int]:
    if not phones:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE phone = ANY(%s)", (phones,))
        return [int(r[0]) for r in cur.fetchall()]


def seed_demo_carts(conn, parent_user_ids: List[int], offer_ids: List[int], cfg) -> None:
    """
    Creates carts + cart_items for:
      - cfg.demo_cart_users random parents
      - PLUS always all SPECIAL parent users
    """
    if not offer_ids:
        print("[seed_carts] skipped: no offers")
        return

    rng = random.Random(cfg.rng_seed + 210)
    demo_users = min(int(cfg.demo_cart_users), len(parent_user_ids))
    picked = rng.sample(parent_user_ids, k=demo_users) if demo_users > 0 else []

    # force special parents
    special_ids = _resolve_user_ids_by_phone(conn, _special_parent_phones())
    for sid in special_ids:
        if sid not in picked:
            picked.append(sid)

    items_per_user = max(1, int(cfg.demo_cart_items_per_user))
    min_qty = max(1, int(getattr(cfg, "demo_cart_min_qty", 1)))
    max_qty = max(min_qty, int(getattr(cfg, "demo_cart_max_qty", 3)))

    with conn.cursor() as cur:
        # carts
        cur.executemany(
            """
            INSERT INTO carts (parent_user_id)
            VALUES (%s)
            ON CONFLICT (parent_user_id) DO NOTHING
            """,
            [(uid,) for uid in picked],
        )

        # cart items
        for uid in picked:
            cur.execute("SELECT id FROM carts WHERE parent_user_id=%s", (uid,))
            cart_id = int(cur.fetchone()[0])

            # use a stable set of offers per user to keep distribution wide
            offers = rng.sample(offer_ids, k=min(items_per_user, len(offer_ids)))
            rows = []
            for oid in offers:
                qty = rng.randint(min_qty, max_qty)
                rows.append((cart_id, oid, qty))

            cur.executemany(
                """
                INSERT INTO cart_items (cart_id, store_offer_id, qty)
                VALUES (%s,%s,%s)
                ON CONFLICT (cart_id, store_offer_id) DO UPDATE SET
                  qty = EXCLUDED.qty,
                  updated_at = now()
                """,
                rows,
            )

    print(f"[seed_carts] carts={len(picked)} items/user~{items_per_user} (includes special users)")
