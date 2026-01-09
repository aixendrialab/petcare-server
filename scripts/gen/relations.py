# scripts/gen/relations.py
from __future__ import annotations
import random
from typing import List

def seed_relations(conn, product_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 51)
    n = len(product_ids)
    if n < 5:
        return

    rows = []
    cover = int(n * float(cfg.relations_coverage_pct))
    cover = max(1, cover)

    sample_products = rng.sample(product_ids, k=min(cover, n))
    for pid in sample_products:
        # pick distinct related ids
        pool = rng.sample(product_ids, k=min(200, n))
        pool = [x for x in pool if x != pid]
        rng.shuffle(pool)

        def take(k: int):
            out = pool[:k]
            del pool[:k]
            return out

        for rid in take(int(cfg.similar_per_product)):
            rows.append((pid, rid, "SIMILAR", rng.randint(50, 120)))
        for rid in take(int(cfg.also_like_per_product)):
            rows.append((pid, rid, "ALSO_LIKE", rng.randint(40, 110)))
        for rid in take(int(cfg.fbt_per_product)):
            rows.append((pid, rid, "FBT", rng.randint(80, 140)))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO item_relations (product_id, related_product_id, relation_type, weight)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )
