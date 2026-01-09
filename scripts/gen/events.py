# scripts/gen/events.py
from __future__ import annotations
import random, json
from typing import List

EVENTS = ["VIEW","ADD_TO_CART","WISHLIST","PURCHASE"]

def seed_events(conn, user_ids: List[int], product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 71)
    total = int(cfg.num_events)
    rows = []
    for _ in range(total):
        uid = rng.choice(user_ids)
        pid = rng.choice(product_ids)
        et = rng.choices(EVENTS, weights=[0.78, 0.12, 0.06, 0.04], k=1)[0]
        meta = {"src": "seed"}
        rows.append((uid, pid, et, json.dumps(meta)))

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO user_item_events (user_id, product_id, event_type, meta) VALUES (%s,%s,%s,%s::jsonb)",
            rows,
        )
