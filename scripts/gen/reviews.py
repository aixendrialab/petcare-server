# scripts/gen/reviews.py
from __future__ import annotations

import random
from typing import List, Sequence, Tuple


BODIES = [
    "Great quality and fast delivery.",
    "Value for money. My pet loved it.",
    "Good packaging. Works as expected.",
    "Decent product, would buy again.",
    "Not bad. Could be better.",
    "My dog is obsessed with this. Helps with boredom.",
    "Fits well and feels sturdy. Good material.",
    "Smells a bit strong at first, but overall okay.",
    "Would recommend. Good results after a week.",
    "Perfect for daily use. Will reorder.",
]

TITLES = ["Great", "Nice", "Okay", "Loved it", "Worth it", "Good buy", "Super", "Not bad"]


def seed_reviews(conn, product_ids: List[int], user_ids: List[int], cfg) -> None:
    rng = random.Random(cfg.rng_seed + 61)

    if not product_ids or not user_ids:
        print("[seed_reviews] skipped (no products/users)")
        return

    # ----------------------------
    # Decide how many reviews
    # ----------------------------
    if getattr(cfg, "reviews_mode", "sparse") == "dense":
        per_prod = int(getattr(cfg, "reviews_per_product", 50))
        total = len(product_ids) * per_prod
        print(f"[seed_reviews] dense mode: {len(product_ids)} products * {per_prod} = {total} reviews")
        _seed_dense(conn, product_ids, user_ids, cfg, rng, per_prod)
    else:
        total = int(getattr(cfg, "num_reviews", 1000))
        print(f"[seed_reviews] sparse mode: total reviews={total}")
        _seed_sparse(conn, product_ids, user_ids, cfg, rng, total)


def _seed_sparse(conn, product_ids: Sequence[int], user_ids: Sequence[int], cfg, rng: random.Random, total: int) -> None:
    rows: List[Tuple] = []
    verified_rate = float(getattr(cfg, "reviews_verified_rate", 0.4))

    for _ in range(total):
        pid = rng.choice(product_ids)
        uid = rng.choice(user_ids)
        rating = rng.randint(3, 5) if rng.random() < 0.85 else rng.randint(1, 3)
        title = rng.choice(TITLES)
        body = rng.choice(BODIES)
        verified = (rng.random() < verified_rate)
        rows.append((pid, None, uid, rating, title, body, verified))

    _insert_reviews(conn, rows, cfg)


def _seed_dense(conn, product_ids: Sequence[int], user_ids: Sequence[int], cfg, rng: random.Random, per_prod: int) -> None:
    # Need at least per_prod distinct users to avoid conflict storms
    if len(user_ids) < per_prod:
        raise RuntimeError(f"[seed_reviews] dense mode needs >= {per_prod} users but only have {len(user_ids)}")

    verified_rate = float(getattr(cfg, "reviews_verified_rate", 0.4))
    rows: List[Tuple] = []

    # Batch by product to keep it deterministic
    for pid in product_ids:
        chosen_users = rng.sample(user_ids, k=per_prod)
        for uid in chosen_users:
            rating = rng.randint(3, 5) if rng.random() < 0.88 else rng.randint(1, 3)
            title = rng.choice(TITLES)
            body = rng.choice(BODIES)
            verified = (rng.random() < verified_rate)
            rows.append((pid, None, uid, rating, title, body, verified))

        # flush periodically to avoid huge memory
        if len(rows) >= int(cfg.batch_size) * 10:
            _insert_reviews(conn, rows, cfg)
            rows.clear()

    if rows:
        _insert_reviews(conn, rows, cfg)


def _insert_reviews(conn, rows: List[Tuple], cfg) -> None:
    if not rows:
        return

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (product_id, user_id) DO NOTHING
            """,
            rows,
        )

    # Optional: review_media + votes
    _seed_review_media(conn, cfg)
    _seed_review_votes(conn, cfg)


def _seed_review_media(conn, cfg) -> None:
    rate = float(getattr(cfg, "reviews_media_rate", 0.1))
    if rate <= 0:
        return

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM item_reviews ORDER BY id DESC LIMIT 50000")
        review_ids = [r[0] for r in cur.fetchall()]

    if not review_ids:
        return

    rng = random.Random(cfg.rng_seed + 62)
    picked = [rid for rid in review_ids if rng.random() < rate]
    rows = []
    for rid in picked:
        # lightweight placeholder images
        rows.append((rid, "IMAGE", f"https://picsum.photos/seed/rev{rid}/900/900", 1))

    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO review_media (review_id, media_type, uri, sort_order)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )


def _seed_review_votes(conn, cfg) -> None:
    rate = float(getattr(cfg, "review_votes_rate", 0.3))
    if rate <= 0:
        return

    rng = random.Random(cfg.rng_seed + 63)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM item_reviews ORDER BY id DESC LIMIT 50000")
        review_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM users ORDER BY id DESC")
        user_ids = [r[0] for r in cur.fetchall()]

    if not review_ids or not user_ids:
        return

    rows = []
    for rid in review_ids:
        if rng.random() > rate:
            continue
        # 1–3 votes per picked review
        k = 1 + (1 if rng.random() < 0.35 else 0) + (1 if rng.random() < 0.15 else 0)
        voters = rng.sample(user_ids, k=min(k, len(user_ids)))
        for uid in voters:
            is_helpful = rng.random() < 0.85
            rows.append((rid, uid, is_helpful))

        if len(rows) >= int(cfg.batch_size) * 10:
            _insert_votes(conn, rows)
            rows.clear()

    if rows:
        _insert_votes(conn, rows)


def _insert_votes(conn, rows: List[Tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO review_votes (review_id, user_id, is_helpful)
            VALUES (%s,%s,%s)
            ON CONFLICT (review_id, user_id) DO UPDATE SET
              is_helpful=EXCLUDED.is_helpful,
              created_at=now()
            """,
            rows,
        )
