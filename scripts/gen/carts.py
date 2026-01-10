# scripts/gen/carts.py
from __future__ import annotations

import random
from typing import List

from scripts.gen.specials import SPECIAL_USERS


def _special_parent_phones() -> List[str]:
    return [phone for phone, _name, _email, roles in SPECIAL_USERS if "parent" in roles]


def _resolve_user_ids_by_phone(conn, phones: List[str]) -> List[int]:
    if not phones:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE phone = ANY(%s)", (phones,))
        return [int(r[0]) for r in cur.fetchall()]


def seed_demo_carts(conn, parent_user_ids: List[int], offer_ids: List[int], cfg) -> None:
    """
    ✅ Guarantees:
      - EVERY parent gets a cart row
      - EVERY parent gets a few cart items
      - ALWAYS includes special parent users (even if not passed in parent_user_ids)
    Uses:
      carts(parent_user_id)
      cart_items(cart_id, store_offer_id, qty, updated_at)
    """
    if not parent_user_ids:
        print("[seed_carts] skipped: no parents")
        return
    if not offer_ids:
        print("[seed_carts] skipped: no offers")
        return

    rng = random.Random(cfg.rng_seed + 210)

    # ✅ UNION: ensure special parents are included
    special_ids = _resolve_user_ids_by_phone(conn, _special_parent_phones())
    all_parents = list(dict.fromkeys(list(parent_user_ids) + special_ids))

    items_per_user = max(1, int(getattr(cfg, "demo_cart_items_per_user", 6) or 6))
    min_qty = max(1, int(getattr(cfg, "demo_cart_min_qty", 1) or 1))
    max_qty = max(min_qty, int(getattr(cfg, "demo_cart_max_qty", 3) or 3))

    # For better perf: pick from a stable offer pool instead of full offer_ids each time
    offer_pool_size = min(len(offer_ids), max(2000, items_per_user * 200))
    offer_pool = (
        rng.sample(offer_ids, k=offer_pool_size)
        if len(offer_ids) > offer_pool_size
        else offer_ids
    )

    with conn.cursor() as cur:
        # 1) Ensure carts exist for all parents
        cur.executemany(
            """
            INSERT INTO carts (parent_user_id)
            VALUES (%s)
            ON CONFLICT (parent_user_id) DO NOTHING
            """,
            [(uid,) for uid in all_parents],
        )

        # 2) Load cart ids for all parents
        cur.execute(
            "SELECT id, parent_user_id FROM carts WHERE parent_user_id = ANY(%s)",
            (all_parents,),
        )
        cart_rows = cur.fetchall()  # (cart_id, parent_user_id)

        # 3) Upsert items
        #    We DO NOT delete old items; we update/insert to keep it idempotent
        for cart_id, parent_id in cart_rows:
            cart_id = int(cart_id)

            offers = rng.sample(offer_pool, k=min(items_per_user, len(offer_pool)))
            rows = []
            for oid in offers:
                qty = rng.randint(min_qty, max_qty)
                rows.append((cart_id, int(oid), int(qty)))

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

    print(f"[seed_carts] carts={len(all_parents)} items/user~{items_per_user} (all parents + specials)")
