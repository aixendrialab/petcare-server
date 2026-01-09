# scripts/gen/main.py
from __future__ import annotations

import argparse
import time

from scripts.gen.context import SeedContext
from scripts.gen.db import get_conn
from scripts.gen.reset import truncate_all
from scripts.gen.config import SeedConfig

from scripts.gen.catalog import seed_media, seed_specs, seed_tags
from scripts.gen.offers import seed_offers
from scripts.gen.promotions import seed_promotions_all
from scripts.gen.relations import seed_relations
from scripts.gen.reviews import seed_reviews
from scripts.gen.events import seed_events

# NEW: demo cart filler (make sure this file exists)
from scripts.gen.carts import seed_demo_carts


def seed_all(dsn: str, cfg: SeedConfig) -> None:
    with get_conn(dsn) as conn:
        print("[seed] truncate_all...")
        truncate_all(conn)

        ctx = SeedContext(cfg=cfg)

        print("[seed] ensure_users...")
        ctx.ensure_users(conn)
        print(f"[seed] users created: {len(ctx.user_ids)}")

        print("[seed] ensure_store_owners...")
        ctx.ensure_store_owners(conn)
        print(f"[seed] store owners assigned: {len(ctx.owner_ids)}")

        print("[seed] ensure_stores...")
        ctx.ensure_stores(conn)
        print(f"[seed] stores created: {len(ctx.store_ids)}")

        print("[seed] ensure_products...")
        ctx.ensure_products(conn)
        print(f"[seed] products created: {len(ctx.product_ids)}")

        print("[seed] ensure_skus...")
        ctx.ensure_skus(conn)
        print(f"[seed] skus created: {len(ctx.sku_ids)}")

        print("[seed] seed_media/specs/tags...")
        seed_media(conn, ctx.product_ids, cfg)
        seed_specs(conn, ctx.product_ids, cfg)
        seed_tags(conn, ctx.product_ids, cfg)

        print("[seed] seed_offers...")
        offer_ids = seed_offers(conn, ctx.store_ids, ctx.sku_ids, cfg)
        print(f"[seed] offers total: {len(offer_ids)}")

        # NEW: demo carts (needs offers)
        if cfg.demo_cart:
            print("[seed] seed_demo_carts...")
            seed_demo_carts(conn, ctx.user_ids, offer_ids, cfg)

        print("[seed] seed_promotions...")
        seed_promotions_all(conn, offer_ids, cfg)

        print("[seed] seed_relations...")
        seed_relations(conn, ctx.product_ids, cfg)

        print("[seed] seed_reviews...")
        seed_reviews(conn, ctx.product_ids, ctx.user_ids, cfg)

        print("[seed] seed_events...")
        seed_events(conn, ctx.user_ids, ctx.product_ids, cfg)

        print("[seed] commit...")
        conn.commit()

        # Counts must be fetched INSIDE cursor context
        print("[seed] counts...")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM users) AS users,
                  (SELECT COUNT(*) FROM provider_stores) AS stores,
                  (SELECT COUNT(*) FROM catalog_products) AS products,
                  (SELECT COUNT(*) FROM catalog_skus) AS skus,
                  (SELECT COUNT(*) FROM store_offers) AS offers,
                  (SELECT COUNT(*) FROM promotions) AS promos,
                  (SELECT COUNT(*) FROM promotion_targets) AS promo_targets,
                  (SELECT COUNT(*) FROM item_reviews) AS reviews,
                  (SELECT COUNT(*) FROM user_item_events) AS events,
                  (SELECT COUNT(*) FROM item_relations) AS relations,
                  (SELECT COUNT(*) FROM carts) AS carts,
                  (SELECT COUNT(*) FROM cart_items) AS cart_items
                """
            )
            row = cur.fetchone()

        (
            users, stores, products, skus, offers,
            promos, promo_targets, reviews, events, relations,
            carts, cart_items
        ) = row

        print(
            "[seed] counts | "
            f"users={users} stores={stores} products={products} skus={skus} offers={offers} "
            f"promos={promos} promo_targets={promo_targets} "
            f"reviews={reviews} events={events} relations={relations} "
            f"carts={carts} cart_items={cart_items}"
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()

    p.add_argument("--dsn", required=True)

    # Primary knobs you already use
    p.add_argument("--products", type=int, default=50_000)
    p.add_argument("--stores", type=int, default=100)
    p.add_argument("--reviews", type=int, default=1_000)
    p.add_argument("--events-per-user", type=int, default=30)
    p.add_argument("--relations-per-product", type=int, default=8)
    p.add_argument("--batch-size", type=int, default=5000)
    p.add_argument("--demo-cart", action="store_true")
    p.add_argument("--rng-seed", type=int, default=1337)
    p.add_argument("--num-users", type=int, default=300)
    p.add_argument("--num-store-owners", type=int, default=120)

    # NEW knobs (optional)
    p.add_argument("--avg-skus-per-product", type=float, default=1.4)
    p.add_argument("--offers-per-sku", type=float, default=1.05)

    p.add_argument("--num-promotions", type=int, default=120)
    p.add_argument("--promo-attach-rate", type=float, default=0.12)

    p.add_argument("--reviews-mode", choices=["sparse", "dense"], default="sparse")
    p.add_argument("--reviews-per-product", type=int, default=50)

    p.add_argument("--demo-cart-users", type=int, default=50)
    p.add_argument("--demo-cart-items-per-user", type=int, default=10)

    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # --------- auto-adjust (never fail due to too-small users/owners) ----------
    # need at least one user per store owner in practice
    num_users = max(args.num_users, args.stores)
    num_owners = max(args.num_store_owners, args.stores)

    if num_users != args.num_users:
        print(f"[seed] auto-adjust: num_users {args.num_users} -> {num_users} (must cover stores)")
    if num_owners != args.num_store_owners:
        print(f"[seed] auto-adjust: num_store_owners {args.num_store_owners} -> {num_owners} (must cover stores)")

    cfg = SeedConfig(
        rng_seed=args.rng_seed,
        batch_size=args.batch_size,

        num_users=num_users,
        num_store_owners=num_owners,
        num_stores=args.stores,
        num_products=args.products,

        # reviews/events
        num_reviews=args.reviews,
        events_per_user=int(args.events_per_user),

        # richness
        avg_skus_per_product=float(args.avg_skus_per_product),
        offers_per_sku=float(args.offers_per_sku),

        # promos
        num_promotions=int(args.num_promotions),
        promo_attach_rate=float(args.promo_attach_rate),

        # reviews mode
        reviews_mode=args.reviews_mode,
        reviews_per_product=int(args.reviews_per_product),

        # demo cart
        demo_cart=bool(args.demo_cart),
        demo_cart_users=int(args.demo_cart_users),
        demo_cart_items_per_user=int(args.demo_cart_items_per_user),
    )

    # derived fields used by other seed modules
    cfg.num_events = cfg.num_users * int(args.events_per_user)
    cfg.similar_per_product = int(args.relations_per_product)
    cfg.also_like_per_product = max(2, int(args.relations_per_product // 2))
    cfg.fbt_per_product = max(1, int(args.relations_per_product // 4))

    print("[seed] starting")
    print(
        f"[seed] users={cfg.num_users} owners={cfg.num_store_owners} stores={cfg.num_stores} "
        f"products={cfg.num_products} skus~{cfg.avg_skus_per_product} offers~{cfg.offers_per_sku} "
        f"reviews={cfg.num_reviews} mode={cfg.reviews_mode} "
        f"events={cfg.num_events} rel(sim={cfg.similar_per_product},also={cfg.also_like_per_product},fbt={cfg.fbt_per_product}) "
        f"promos={cfg.num_promotions} attach={cfg.promo_attach_rate} "
        f"demo_cart={cfg.demo_cart} carts={cfg.demo_cart_users} items/cart={cfg.demo_cart_items_per_user} "
        f"batch={cfg.batch_size}"
    )

    t0 = time.time()
    seed_all(args.dsn, cfg)
    print(f"[seed] done in {time.time() - t0:.1f}s")
