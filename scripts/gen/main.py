# scripts/gen/main.py
from __future__ import annotations

import argparse
import time
import random
from typing import List

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
from scripts.gen.carts import seed_demo_carts
from scripts.gen.orders import seed_demo_orders

from scripts.gen.vets import seed_vets
from scripts.gen.pets import seed_parents, seed_pets
from scripts.gen.appointments import seed_appointments
from scripts.gen.consults import seed_consults
from scripts.gen.vaccines import seed_vaccine_catalog, seed_pet_vaccines

# ✅ keep specials in one place (specials.py is fine)
from scripts.gen.specials import SPECIAL_USERS


def _pick_unique(rng: random.Random, pool: List[int], k: int) -> List[int]:
    if not pool or k <= 0:
        return []
    k = min(k, len(pool))
    return rng.sample(pool, k=k)


def _resolve_user_ids_by_phone(conn, phones: List[str]) -> List[int]:
    if not phones:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE phone = ANY(%s) ORDER BY id", (phones,))
        return [int(r[0]) for r in cur.fetchall()]


def _special_parent_ids(conn) -> List[int]:
    phones = [p for (p, _n, _e, roles) in SPECIAL_USERS if "parent" in roles]
    return _resolve_user_ids_by_phone(conn, phones)


def _special_vet_ids(conn) -> List[int]:
    phones = [p for (p, _n, _e, roles) in SPECIAL_USERS if "vet" in roles]
    return _resolve_user_ids_by_phone(conn, phones)


def seed_all(dsn: str, cfg: SeedConfig) -> None:
    with get_conn(dsn) as conn:
        print("[seed] truncate_all...")
        truncate_all(conn)

        ctx = SeedContext(cfg=cfg)

        # -------------------------
        # USERS / STORES / CATALOG
        # -------------------------
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

        # -------------------------
        # MANDATORY: VETS + PARENTS + PETS + APPTS + CONSULTS + VACCINES
        # -------------------------
        rng = random.Random(cfg.rng_seed + 699)

        # Pick vets
        num_vets = min(int(cfg.num_vets), len(ctx.user_ids))
        vet_user_ids = _pick_unique(rng, ctx.user_ids, num_vets)

        # Force special vets into pool
        special_vets = _special_vet_ids(conn)
        for vid in special_vets:
            if vid not in vet_user_ids and vid in ctx.user_ids:
                vet_user_ids.append(vid)

        vet_set = set(vet_user_ids)

        # Pick parents from remaining users
        remaining = [u for u in ctx.user_ids if u not in vet_set]
        num_parents = min(int(cfg.num_parents), len(remaining))
        parent_user_ids = _pick_unique(rng, remaining, num_parents)

        # ✅ FIX: Force special parents into pool (do NOT require pid in remaining)
        special_parents = _special_parent_ids(conn)
        for pid in special_parents:
            if pid not in parent_user_ids and pid in ctx.user_ids:
                parent_user_ids.append(pid)

        # ✅ Canonical list for all parent-dependent seeders
        parents_for_pet_flow = list(dict.fromkeys(parent_user_ids + special_parents))

        # Ensure minimum pets/parent
        cfg.pets_per_parent = max(2, int(cfg.pets_per_parent))
        cfg.appointments_per_parent = max(2, int(cfg.appointments_per_parent))

        print(
            f"[seed] vet-flow | vets={len(vet_user_ids)} parents={len(parents_for_pet_flow)} "
            f"pets/parent={cfg.pets_per_parent} appt/parent={cfg.appointments_per_parent} slot={cfg.slot_minutes}m"
        )

        print("[seed] seed_vets (profiles/locations/slot_settings/overrides)...")
        seed_vets(conn, vet_user_ids, cfg)

        print("[seed] seed_parents (user_roles)...")
        seed_parents(conn, parents_for_pet_flow)

        print("[seed] seed_pets...")
        pet_ids_by_parent = seed_pets(conn, parents_for_pet_flow, cfg)
        all_pet_ids = [pid for arr in pet_ids_by_parent.values() for pid in arr]
        print(f"[seed] pets created: {len(all_pet_ids)} (expected ~{len(parents_for_pet_flow) * cfg.pets_per_parent})")

        print("[seed] seed_vaccine_catalog...")
        seed_vaccine_catalog(conn)

        print("[seed] seed_pet_vaccines (plans/items/records)...")
        vstats = seed_pet_vaccines(conn, all_pet_ids, vet_user_ids, cfg)
        print(
            "[seed] vaccines | "
            f"plans={vstats.get('plans')} plan_items={vstats.get('plan_items')} "
            f"records={vstats.get('records')} completed_items={vstats.get('completed_items')}"
        )

        print("[seed] seed_appointments...")
        attempted = seed_appointments(conn, vet_user_ids, parents_for_pet_flow, pet_ids_by_parent, cfg)
        print(f"[seed] appointments attempted={attempted} (insert best-effort / conflicts ignored)")

        print("[seed] seed_consults...")
        consult_cnt = seed_consults(conn, cfg, limit=int(getattr(cfg, "max_consults", 20000)))
        print(f"[seed] consults created: {consult_cnt}")

        # -------------------------
        # COMMERCE ENRICHMENTS
        # -------------------------
        print("[seed] seed_media/specs/tags...")
        seed_media(conn, ctx.product_ids, cfg)
        seed_specs(conn, ctx.product_ids, cfg)
        seed_tags(conn, ctx.product_ids, cfg)

        print("[seed] seed_offers...")
        offer_ids = seed_offers(conn, ctx.store_ids, ctx.sku_ids, cfg)
        print(f"[seed] offers total: {len(offer_ids)}")

        #if cfg.demo_cart:
        print("[seed] seed_demo_carts...")
        # ✅ carts for parents in parent-flow
        seed_demo_carts(conn, parents_for_pet_flow, offer_ids, cfg)

        print("[seed] seed_promotions...")
        seed_promotions_all(conn, offer_ids, cfg)

        print("[seed] seed_relations...")
        seed_relations(conn, ctx.product_ids, cfg)

        print("[seed] seed_reviews...")
        seed_reviews(conn, ctx.product_ids, ctx.user_ids, cfg)

        print("[seed] seed_events...")
        seed_events(conn, ctx.user_ids, ctx.product_ids, cfg)

        #if bool(getattr(cfg, "demo_orders", True)):
        print("[seed] seed_demo_orders...")
        # ✅ orders for parents in parent-flow
        seed_demo_orders(conn, parents_for_pet_flow, offer_ids, cfg)

        print("[seed] commit...")
        conn.commit()

        # (counts block unchanged)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True)

    p.add_argument("--products", type=int, default=50_000)
    p.add_argument("--stores", type=int, default=100)

    # Legacy (kept for compatibility)
    p.add_argument("--num-users", type=int, default=300)  # legacy (treated as extra if > sum roles)

    # ✅ new
    p.add_argument("--num-extra-users", type=int, default=0)

    p.add_argument("--num-store-owners", type=int, default=120)

    p.add_argument("--avg-skus-per-product", type=float, default=1.4)
    p.add_argument("--offers-per-sku", type=float, default=1.05)

    p.add_argument("--num-promotions", type=int, default=120)
    p.add_argument("--promo-attach-rate", type=float, default=0.12)

    p.add_argument("--reviews", type=int, default=1_000)
    p.add_argument("--reviews-mode", choices=["sparse", "dense"], default="sparse")
    p.add_argument("--reviews-per-product", type=int, default=50)

    p.add_argument("--events-per-user", type=int, default=30)
    p.add_argument("--relations-per-product", type=int, default=8)

    p.add_argument("--batch-size", type=int, default=5000)
    p.add_argument("--rng-seed", type=int, default=1337)

    p.add_argument("--demo-cart", action="store_true")
    p.add_argument("--demo-cart-users", type=int, default=200)
    p.add_argument("--demo-cart-items-per-user", type=int, default=10)

    # vet mandatory knobs
    p.add_argument("--num-vets", type=int, default=50)
    p.add_argument("--num-parents", type=int, default=500)
    p.add_argument("--pets-per-parent", type=int, default=2)
    p.add_argument("--appointments-per-parent", type=int, default=6)
    p.add_argument("--slot-minutes", type=int, default=2)

    # orders knobs
    p.add_argument("--demo-orders-users", type=int, default=200)
    p.add_argument("--delivered-orders-per-user", type=int, default=1)
    p.add_argument("--inprogress-orders-per-user", type=int, default=1)

    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # ✅ role-first user math
    required = (
        int(args.num_parents)
        + int(args.num_vets)
        + int(args.num_store_owners)
        + int(args.num_extra_users)
    )

    # legacy: if num-users is bigger, treat it as extra users beyond the role sum
    legacy_extra = max(0, int(args.num_users) - required)
    num_users = required + legacy_extra

    # owners must cover stores
    num_owners = max(int(args.num_store_owners), int(args.stores))

    cfg = SeedConfig(
        rng_seed=args.rng_seed,
        batch_size=args.batch_size,

        num_users=num_users,
        num_store_owners=num_owners,
        num_stores=args.stores,
        num_products=args.products,

        avg_skus_per_product=float(args.avg_skus_per_product),
        offers_per_sku=float(args.offers_per_sku),

        num_promotions=int(args.num_promotions),
        promo_attach_rate=float(args.promo_attach_rate),

        num_reviews=int(args.reviews),
        reviews_mode=args.reviews_mode,
        reviews_per_product=int(args.reviews_per_product),

        events_per_user=int(args.events_per_user),

        demo_cart=bool(args.demo_cart),
        demo_cart_users=int(args.demo_cart_users),
        demo_cart_items_per_user=int(args.demo_cart_items_per_user),

        # mandatory vet flow
        num_vets=int(args.num_vets),
        num_parents=int(args.num_parents),
        pets_per_parent=max(2, int(args.pets_per_parent)),
        appointments_per_parent=int(args.appointments_per_parent),
        slot_minutes=max(2, int(args.slot_minutes)),

        # orders
        demo_orders=True,
        demo_orders_users=int(args.demo_orders_users),
        delivered_orders_per_user=int(args.delivered_orders_per_user),
        inprogress_orders_per_user=int(args.inprogress_orders_per_user),
    )

    # derived
    cfg.num_events = cfg.num_users * cfg.events_per_user

    rel = int(args.relations_per_product)
    cfg.similar_per_product = rel
    cfg.also_like_per_product = max(2, rel // 2)
    cfg.fbt_per_product = max(1, rel // 4)

    print("[seed] starting")
    print(
        f"[seed] users={cfg.num_users} owners={cfg.num_store_owners} stores={cfg.num_stores} "
        f"products={cfg.num_products} skus~{cfg.avg_skus_per_product} offers~{cfg.offers_per_sku} "
        f"reviews={cfg.num_reviews} mode={cfg.reviews_mode} "
        f"events={cfg.num_events} promos={cfg.num_promotions} attach={cfg.promo_attach_rate} "
        f"vet(vets={cfg.num_vets},parents={cfg.num_parents},pets/parent={cfg.pets_per_parent},appts/parent={cfg.appointments_per_parent},slot={cfg.slot_minutes}m) "
        f"demo_cart={cfg.demo_cart} carts={cfg.demo_cart_users} items/cart={cfg.demo_cart_items_per_user} "
        f"orders_users={cfg.demo_orders_users} "
        f"batch={cfg.batch_size}"
    )

    t0 = time.time()
    seed_all(args.dsn, cfg)
    print(f"[seed] done in {time.time() - t0:.1f}s")
