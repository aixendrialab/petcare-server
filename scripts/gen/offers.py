# scripts/gen/offers.py
from __future__ import annotations
import random
from typing import List

def seed_offers(conn, store_ids: List[int], sku_ids: List[int], cfg) -> List[int]:
    rng = random.Random(cfg.rng_seed + 31)

    offers = []
    stores_n = len(store_ids)
    for sku_id in sku_ids:
        # 1+ offers per sku (avg)
        k = 1
        if rng.random() < (cfg.offers_per_sku - 1.0):
            k += 1

        for j in range(k):
            store_id = store_ids[(sku_id + j) % stores_n]
            price = rng.randint(49, 1999)
            mrp = price + rng.randint(0, 600)
            disc = int(round((mrp - price) * 100 / mrp)) if mrp > price else 0
            stock = rng.randint(0, 200)
            offers.append((
                store_id, sku_id, True,
                "INR", float(price), float(mrp), disc,
                stock, rng.randint(5, 25),
                0.0 if rng.random() < 0.6 else float(rng.choice([29,49,79])),
                rng.choice(["Fast delivery","Arriving soon","Delivery in 2-3 days"]),
                rng.randint(1,3), rng.randint(2,5),
                True if rng.random() < 0.7 else False,
                None
            ))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO store_offers
              (store_id, sku_id, is_active, currency, price, mrp, discount_pct,
               stock_qty, reorder_level, shipping_fee, eta_text, eta_days_min, eta_days_max,
               returnable, warranty_months)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (store_id, sku_id) DO NOTHING
            """,
            offers
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM store_offers ORDER BY id ASC")
        return [int(r[0]) for r in cur.fetchall()]
