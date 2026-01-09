# scripts/gen/carts.py
from __future__ import annotations

import random
from typing import List


def seed_demo_carts(conn, user_ids: List[int], offer_ids: List[int], cfg) -> None:
    if not getattr(cfg, "demo_cart", False):
        return

    if not user_ids or not offer_ids:
        print("[seed_demo_carts] skipped (no users/offers)")
        return

    rng = random.Random(cfg.rng_seed + 91)

    n_users = min(int(getattr(cfg, "demo_cart_users", 50)), len(user_ids))
    items_per = int(getattr(cfg, "demo_cart_items_per_user", 10))

    chosen_users = rng.sample(user_ids, k=n_users)

    # create carts
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO carts (parent_user_id)
            VALUES (%s)
            ON CONFLICT (parent_user_id) DO NOTHING
            """,
            [(uid,) for uid in chosen_users],
        )

        cur.execute(
            "SELECT id, parent_user_id FROM carts WHERE parent_user_id = ANY(%s)",
            (chosen_users,),
        )
        carts = cur.fetchall()  # (cart_id, user_id)

    # add items
    rows = []
    for (cart_id, _uid) in carts:
        picks = rng.sample(offer_ids, k=min(items_per, len(offer_ids)))
        for offer_id in picks:
            qty = 1 + (1 if rng.random() < 0.25 else 0)
            rows.append((int(cart_id), int(offer_id), int(qty)))

    with conn.cursor() as cur:
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

    print(f"[seed_demo_carts] carts={len(carts)} items={len(rows)} (items_per_user={items_per})")
