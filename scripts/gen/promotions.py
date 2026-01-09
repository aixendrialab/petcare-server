# scripts/gen/promotions.py
from __future__ import annotations

import random
from typing import List, Optional, Sequence


def _weighted_choice(rng: random.Random, items: Sequence[str], weights: Sequence[float]) -> str:
    # simple stable weighted choice without numpy
    x = rng.random() * sum(weights)
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if x <= acc:
            return it
    return items[-1]


def seed_promotions(conn, cfg) -> List[int]:
    rng = random.Random(cfg.rng_seed + 41)

    promo_types = ["DISCOUNT", "COUPON", "BANK", "BUNDLE"]
    weights = getattr(cfg, "promo_type_weights", (0.7, 0.2, 0.07, 0.03))
    n = int(getattr(cfg, "num_promotions", 120))
    duration_days = int(getattr(cfg, "promo_duration_days", 30))

    disc_min = int(getattr(cfg, "promo_discount_pct_min", 5))
    disc_max = int(getattr(cfg, "promo_discount_pct_max", 25))
    bank_min = int(getattr(cfg, "promo_bank_pct_min", 3))
    bank_max = int(getattr(cfg, "promo_bank_pct_max", 15))
    coupon_amounts = list(getattr(cfg, "coupon_amounts", (50, 100, 150, 200)))

    rows = []
    for _ in range(n):
        promo_type = _weighted_choice(rng, promo_types, weights)

        title_map = {
            "DISCOUNT": "Limited time deal",
            "COUPON": "Coupon",
            "BANK": "Bank offer",
            "BUNDLE": "Bundle price",
        }
        title = title_map[promo_type]
        subtitle = "Auto-generated promo"

        discount_pct: Optional[int] = None
        discount_amount: Optional[float] = None

        if promo_type == "DISCOUNT":
            discount_pct = rng.randint(disc_min, disc_max)
            subtitle = f"Save {discount_pct}% today"
        elif promo_type == "COUPON":
            amt = int(rng.choice(coupon_amounts))
            discount_amount = float(amt)
            title = f"₹{amt} coupon"
            subtitle = "On eligible items"
        elif promo_type == "BANK":
            discount_pct = rng.randint(bank_min, bank_max)
            subtitle = f"Extra {discount_pct}% with select cards"
        else:  # BUNDLE
            discount_pct = rng.randint(bank_min, bank_max)
            subtitle = f"Save {discount_pct}% when bundled"

        min_qty = 1
        is_active = True

        # 7 values; valid_from/to handled in SQL with duration_days
        rows.append((title, subtitle, promo_type, discount_pct, discount_amount, min_qty, is_active))

    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO promotions
              (title, subtitle, promo_type, discount_pct, discount_amount, min_qty,
               valid_from, valid_to, is_active)
            VALUES
              (%s,%s,%s,%s,%s,%s,
               now(), now() + interval '{duration_days} days', %s)
            """,
            rows,
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM promotions ORDER BY id ASC")
        return [int(r[0]) for r in cur.fetchall()]


def attach_promotions(conn, promo_ids: List[int], offer_ids: List[int], cfg) -> int:
    rng = random.Random(cfg.rng_seed + 42)

    if not promo_ids or not offer_ids:
        return 0

    attach_rate = float(getattr(cfg, "promo_attach_rate", 0.12))
    max_promos_per_offer = int(getattr(cfg, "max_promos_per_offer", 2))
    two_prob = float(getattr(cfg, "promo_attach_two_prob", 0.2))

    attach_n = max(1, int(len(offer_ids) * attach_rate))
    attach_n = min(attach_n, len(offer_ids))

    chosen_offers = rng.sample(offer_ids, k=attach_n)

    targets = []
    for offer_id in chosen_offers:
        # 1 promo by default; sometimes 2; always bounded by config + population
        k = 1
        if max_promos_per_offer >= 2 and rng.random() < two_prob:
            k = 2
        k = min(k, max_promos_per_offer, len(promo_ids))
        if k <= 0:
            continue

        for pid in rng.sample(promo_ids, k=k):
            targets.append((pid, offer_id))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO promotion_targets (promo_id, store_offer_id)
            VALUES (%s,%s)
            ON CONFLICT DO NOTHING
            """,
            targets,
        )

    return len(targets)


def seed_promotions_all(conn, offer_ids: List[int], cfg) -> None:
    promo_ids = seed_promotions(conn, cfg)
    targets = attach_promotions(conn, promo_ids, offer_ids, cfg)
    print(f"[seed_promotions] promos={len(promo_ids)} targets={targets}")
