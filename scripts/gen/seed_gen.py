#!/usr/bin/env python3
"""
Mass data generator for PetCare commerce v2 schema.

- Executes schema.sql (drop + recreate)
- Seeds:
  users, user_roles, user_addresses,
  brands, tax_classes,
  provider_stores, store_badges,
  catalog_products, catalog_skus, product_media, product_specs, product_tags,
  store_offers, promotions, promotion_targets,
  item_reviews, review_media, review_votes,
  store_reviews, store_review_votes,
  item_questions, item_answers,
  wishlists, wishlist_items,
  user_item_events,
  item_relations,
  carts, cart_items (optional small demo)

Designed for scale: 50k+ products, 100+ stores, etc (configurable).

Requires: psycopg>=3
  pip install "psycopg[binary]"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import re
import string
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import psycopg
from psycopg import sql


# -----------------------------
# Utilities
# -----------------------------

def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def chunked(seq: Sequence[Any], n: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

def rand_phone(rng: random.Random) -> str:
    # India-ish demo phone
    return "+91" + "".join(rng.choice(string.digits) for _ in range(10))

def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:60] or "x"

def pick_weighted(rng: random.Random, items: List[Tuple[Any, float]]) -> Any:
    total = sum(w for _, w in items)
    r = rng.random() * total
    upto = 0.0
    for v, w in items:
        upto += w
        if upto >= r:
            return v
    return items[-1][0]

def inr_money(amount: float) -> float:
    # keep numeric for DB columns; UI wraps to Money
    return round(float(amount), 2)

def loremflickr_uri(tag: str, lock: int) -> str:
    # stable-ish placeholder
    return f"https://loremflickr.com/900/900/{tag}?lock={lock}"

def safe_email(name: str, domain: str, uniq: int) -> str:
    return f"{slugify(name)}{uniq}@{domain}"


# -----------------------------
# Config
# -----------------------------

@dataclass
class SeedConfig:
    seed: int

    # scale knobs
    num_parents: int
    num_store_owners: int
    num_stores: int
    num_brands: int
    num_products: int

    # per product
    min_skus: int
    max_skus: int
    media_per_product: int
    specs_per_product: int
    tags_per_product: int

    # offers
    offers_per_product_min: int
    offers_per_product_max: int
    pct_products_on_promo: float

    # social
    num_reviews: int
    review_media_pct: float
    num_review_votes: int
    num_store_reviews: int
    num_store_review_votes: int
    num_questions: int
    num_answers: int

    # relations/events
    relations_per_product: int
    events_per_user: int

    # operational
    batch_size: int
    create_demo_cart: bool

    # files
    schema_file: str


# -----------------------------
# Domain dictionaries (dog/cat oriented)
# -----------------------------

DOG_FOOD_BRANDS = ["Royal Canin", "Pedigree", "Drools", "Farmina", "Purina", "Acana", "Orijen"]
CAT_FOOD_BRANDS = ["Whiskas", "Royal Canin", "Purina", "Me-O", "Sheba", "Farmina"]

ACCESSORY_BRANDS = ["PetCare", "Goofy Tails", "PawHut", "Trixie", "Kong", "Ferplast"]
MEDICINE_BRANDS = ["Himalaya Pet", "Intas", "Virbac", "Bayer", "Beaphar", "GenericVet"]

DOG_BREEDS = ["Labrador", "Golden Retriever", "Pug", "German Shepherd", "Beagle", "Indie"]
CAT_BREEDS = ["Persian", "Maine Coon", "Siamese", "Bengal", "British Shorthair", "Indie"]

CITIES = [
    ("Vizag", "AP", "530001"),
    ("Hyderabad", "TS", "500001"),
    ("Bengaluru", "KA", "560001"),
    ("Chennai", "TN", "600001"),
    ("Mumbai", "MH", "400001"),
    ("Delhi", "DL", "110001"),
]

CATEGORY_WEIGHTS = [
    ("FOOD", 0.45),
    ("ACCESSORY", 0.35),
    ("MEDICINE", 0.15),
    ("SERVICE", 0.05),
]

TAX_CLASS_MAP = {
    "FOOD": ("GST_5", "23091000", 5.0),
    "ACCESSORY": ("GST_18", "95030010", 18.0),
    "MEDICINE": ("GST_12", "30049099", 12.0),
    "SERVICE": ("GST_18", "999799", 18.0),
}

DEFAULT_STORE_BADGES = ["Trusted seller", "Fast dispatch", "Premium selection", "Licensed pharmacy"]


# -----------------------------
# Bulk insert helpers
# -----------------------------

def exec_sql_file(conn: psycopg.Connection, path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        ddl = f.read()
    # psycopg3 execute can run multi statements
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()

def insert_many(conn: psycopg.Connection, table: str, cols: List[str], rows: List[Tuple[Any, ...]], batch: int) -> None:
    if not rows:
        return
    col_sql = sql.SQL(",").join(sql.Identifier(c) for c in cols)
    placeholders = sql.SQL(",").join(sql.Placeholder() for _ in cols)
    q = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(sql.Identifier(table), col_sql, placeholders)

    with conn.cursor() as cur:
        for chunk in chunked(rows, batch):
            cur.executemany(q, chunk)
    conn.commit()

def insert_many_returning_ids(
    conn,
    table: str,
    cols: List[str],
    rows: Sequence[Sequence[Any]],
    batch_size: int = 1000,
) -> List[int]:
    """
    Inserts many rows and returns generated ids.

    psycopg v3: cursor.executemany(..., returning=True) is REQUIRED
    to fetch RETURNING results.
    """
    if not rows:
        return []

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) RETURNING id"

    out: List[int] = []
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]

            # psycopg v3 supports returning=True
            try:
                cur.executemany(sql, chunk, returning=True)
                out.extend(int(r[0]) for r in cur.fetchall())
            except TypeError:
                # Fallback: psycopg versions/builds without returning=True support
                for params in chunk:
                    cur.execute(sql, params)
                    rid = cur.fetchone()
                    if rid:
                        out.append(int(rid[0]))

    return out

# -----------------------------
# Main generator
# -----------------------------

def build_config(args: argparse.Namespace) -> SeedConfig:
    return SeedConfig(
        seed=args.seed,
        num_parents=args.parents,
        num_store_owners=args.store_owners,
        num_stores=args.stores,
        num_brands=args.brands,
        num_products=args.products,
        min_skus=args.min_skus,
        max_skus=args.max_skus,
        media_per_product=args.media_per_product,
        specs_per_product=args.specs_per_product,
        tags_per_product=args.tags_per_product,
        offers_per_product_min=args.offers_min,
        offers_per_product_max=args.offers_max,
        pct_products_on_promo=args.promo_pct,
        num_reviews=args.reviews,
        review_media_pct=args.review_media_pct,
        num_review_votes=args.review_votes,
        num_store_reviews=args.store_reviews,
        num_store_review_votes=args.store_review_votes,
        num_questions=args.questions,
        num_answers=args.answers,
        relations_per_product=args.relations_per_product,
        events_per_user=args.events_per_user,
        batch_size=args.batch_size,
        create_demo_cart=args.demo_cart,
        schema_file=args.schema_file,
    )

def seed_all(dsn: str, cfg: SeedConfig) -> None:
    rng = random.Random(cfg.seed)

    with psycopg.connect(dsn, autocommit=False) as conn:
        conn.execute("SET client_min_messages TO WARNING;")
        conn.execute("SET timezone TO 'UTC';")

        # 1) Run schema.sql (DROP + CREATE)
        print(f"[seed] executing schema file: {cfg.schema_file}")
        exec_sql_file(conn, cfg.schema_file)

        # 2) tax classes
        tax_rows = [
            ("GST_0", 0.00, "Zero rated"),
            ("GST_5", 5.00, "GST 5%"),
            ("GST_12", 12.00, "GST 12%"),
            ("GST_18", 18.00, "GST 18%"),
        ]
        insert_many(conn, "tax_classes", ["code", "gst_pct", "description"], tax_rows, cfg.batch_size)

        # 3) brands (mix of known + generated)
        base_brands = list(dict.fromkeys(DOG_FOOD_BRANDS + CAT_FOOD_BRANDS + ACCESSORY_BRANDS + MEDICINE_BRANDS))
        while len(base_brands) < cfg.num_brands:
            base_brands.append(f"Brand {len(base_brands)+1}")
        base_brands = base_brands[:cfg.num_brands]

        brand_rows = [(b, f"About {b} - pet oriented brand.", None, None) for b in base_brands]
        brand_ids = insert_many_returning_ids(conn, "brands", ["name", "about", "logo_uri", "website"], brand_rows, cfg.batch_size)
        brand_by_name = {name: bid for name, bid in zip(base_brands, brand_ids)}

        # 4) users: parents + store owners (+ a few extra reviewers)
        users_rows: List[Tuple[str, str, str, str]] = []
        roles_rows: List[Tuple[int, str]] = []

        def add_user(name: str, active_role: str | None, domain="example.com") -> None:
            phone = rand_phone(rng)
            email = safe_email(name, domain, rng.randint(1, 10_000_000))
            users_rows.append((phone, email, name, active_role))

        for i in range(cfg.num_parents):
            add_user(f"Parent {i+1}", "parent", "parents.example.com")

        for i in range(cfg.num_store_owners):
            # mix roles for store owners
            role = pick_weighted(rng, [("vendor", 0.7), ("pharmacist", 0.2), ("hostel", 0.05), ("nutritionist", 0.05)])
            add_user(f"Seller {i+1}", role, "sellers.example.com")

        # reviewers (extra users to allow many reviews without unique constraint collisions)
        reviewers_needed = max(cfg.num_reviews // 3, 500)
        for i in range(reviewers_needed):
            add_user(f"User {i+1}", None, "users.example.com")

        user_ids = insert_many_returning_ids(conn, "users", ["phone", "email", "name", "active_role"], users_rows, cfg.batch_size)

        # assign roles: first N are parents, next M are store owners
        parent_ids = user_ids[:cfg.num_parents]
        owner_ids = user_ids[cfg.num_parents:cfg.num_parents + cfg.num_store_owners]
        misc_user_ids = user_ids[cfg.num_parents + cfg.num_store_owners:]

        # user_roles
        # parents
        roles_rows.extend([(uid, "parent") for uid in parent_ids])
        # store owners: match their active_role in users_rows (we stored string)
        for idx, uid in enumerate(owner_ids):
            active_role = users_rows[cfg.num_parents + idx][3]
            if active_role:
                roles_rows.append((uid, active_role))
        insert_many(conn, "user_roles", ["user_id", "role"], roles_rows, cfg.batch_size)

        # 5) addresses for parents
        addr_rows = []
        for uid in parent_ids:
            city, state, pin = rng.choice(CITIES)
            addr_rows.append((
                uid, "Home", f"Recipient {uid}", rand_phone(rng),
                f"Flat {rng.randint(1,999)}", "Near Park", "Landmark",
                city, state, pin,
                None, None,
                True
            ))
        insert_many(conn, "user_addresses",
                    ["user_id","label","recipient","phone","line1","line2","landmark","city","state","pincode","lat","lng","is_default"],
                    addr_rows, cfg.batch_size)

        # 6) stores (100)
        store_rows = []
        store_owner_pairs = []
        for i in range(cfg.num_stores):
            owner = owner_ids[i % len(owner_ids)]
            role = users_rows[cfg.num_parents + (i % len(owner_ids))][3] or "vendor"
            city, state, pin = rng.choice(CITIES)
            display_name = f"{['Asha','Ravi','Happy','Paws','Pet','Care','Buddy','Tail'][i % 8]} Store {i+1}"
            store_rows.append((
                owner, role, display_name,
                rand_phone(rng),
                safe_email(display_name, "stores.example.com", i+1),
                None,
                f"About {display_name} (dogs/cats focus).",
                "ACTIVE",
                "Main Road", "Near Market", city, state, pin,
                None, None,
                None, None, None
            ))
            store_owner_pairs.append((owner, role))

        # Insert stores
        store_cols = [
            "owner_user_id","role","display_name","phone","email","logo_uri","about","status",
            "address_line1","address_line2","city","state","pincode",
            "license_no","license_valid_till",
            "rating_avg","rating_count","orders_30d"
        ]
        store_ids = insert_many_returning_ids(conn, "provider_stores", store_cols, store_rows, cfg.batch_size)

        # store badges (2 per store)
        badge_rows = []
        for sid in store_ids:
            picks = rng.sample(DEFAULT_STORE_BADGES, k=2)
            for b in picks:
                badge_rows.append((sid, b))
        insert_many(conn, "store_badges", ["store_id","badge"], badge_rows, cfg.batch_size)

        # 7) products + skus + tags + media + specs
        product_rows = []
        for i in range(cfg.num_products):
            cat = pick_weighted(rng, CATEGORY_WEIGHTS)
            if cat == "FOOD":
                brand = rng.choice(DOG_FOOD_BRANDS + CAT_FOOD_BRANDS)
            elif cat == "ACCESSORY":
                brand = rng.choice(ACCESSORY_BRANDS)
            elif cat == "MEDICINE":
                brand = rng.choice(MEDICINE_BRANDS)
            else:
                brand = "PetCare Services"

            brand_id = brand_by_name.get(brand)
            tax_class, hsn, _gst = TAX_CLASS_MAP[cat]

            title, short_desc, desc, variant_theme = make_product_copy(rng, cat, brand, i)
            product_rows.append((
                cat,
                brand_id,
                None if brand_id else brand,
                title,
                short_desc,
                desc,
                None,
                bool(cat == "MEDICINE"),
                hsn,
                tax_class,
                variant_theme,
                True
            ))

        product_cols = [
            "category","brand_id","brand_text","title","short_desc","description","about_brand",
            "prescription_required","hsn_code","tax_class","variant_theme","is_active"
        ]
        product_ids = insert_many_returning_ids(conn, "catalog_products", product_cols, product_rows, cfg.batch_size)

        # SKUs per product
        sku_rows = []
        sku_meta: List[Tuple[int, int, str | None, str | None, str | None]] = []  # (sku_id later), product_id, key, value, pack_label
        # We'll insert SKUs and later map ids by querying sequences is hard; use RETURNING.
        for pid, prow in zip(product_ids, product_rows):
            cat = prow[0]
            variant_theme = prow[10]
            n_skus = rng.randint(cfg.min_skus, cfg.max_skus) if variant_theme else 1
            for sidx in range(n_skus):
                vkey, vval, pack = make_sku_variant(rng, cat, variant_theme, sidx)
                sku_code = f"SKU-{pid}-{sidx}-{slugify(vval or pack or 'std')}".upper()[:40]
                sku_rows.append((pid, vkey, vval, pack, sku_code, sidx + 1, True))
        sku_cols = ["product_id","variant_key","variant_value","pack_label","sku_code","sort_order","is_active"]
        sku_ids = insert_many_returning_ids(conn, "catalog_skus", sku_cols, sku_rows, cfg.batch_size)

        # Build quick lookup: product_id -> list of sku_ids
        product_to_skus: Dict[int, List[int]] = {}
        idx = 0
        for pid, prow in zip(product_ids, product_rows):
            variant_theme = prow[10]
            n_skus = rng.randint(cfg.min_skus, cfg.max_skus) if variant_theme else 1
            # NOTE: must mirror earlier SKU loop. To avoid mismatch, compute deterministic count based on pid:
            # We'll reconstruct by reading back from DB instead of duplicating logic.
            # Safer: query DB once for mapping.
        # Query mapping once
        with conn.cursor() as cur:
            cur.execute("SELECT product_id, id FROM catalog_skus WHERE is_active=TRUE ORDER BY product_id, sort_order, id")
            for product_id, sku_id in cur.fetchall():
                product_to_skus.setdefault(int(product_id), []).append(int(sku_id))
        conn.commit()

        # media/specs/tags
        media_rows = []
        spec_rows = []
        tag_rows = []

        for pid, prow in zip(product_ids, product_rows):
            cat = prow[0]
            brand = prow[2] or (base_brands[0] if prow[1] else "PetCare")

            # media
            for m in range(cfg.media_per_product):
                tag = media_tag_for_category(cat)
                media_rows.append((pid, "IMAGE", loremflickr_uri(tag, lock=(pid * 10 + m + 1)), ["Front","In use","Packaging","Detail","Size"][m % 5], m+1))

            # tags
            tags = tags_for_product(rng, cat, prow[3])
            for t in tags[:cfg.tags_per_product]:
                tag_rows.append((pid, t))

            # specs
            for grp, k, v, so in specs_for_product(rng, cat, prow[3], prow[10])[:cfg.specs_per_product]:
                spec_rows.append((pid, grp, k, v, so))

        insert_many(conn, "product_media", ["product_id","media_type","uri","label","sort_order"], media_rows, cfg.batch_size)
        insert_many(conn, "product_tags", ["product_id","tag"], tag_rows, cfg.batch_size)
        insert_many(conn, "product_specs", ["product_id","spec_group","spec_key","spec_value","sort_order"], spec_rows, cfg.batch_size)

        # 8) store_offers: each product offered by 1..N stores, per sku
        offer_rows = []
        promo_target_candidates: List[int] = []

        # We will need store_offer ids. Insert with RETURNING.
        offer_cols = [
            "store_id","sku_id","is_active","currency","price","mrp","discount_pct",
            "stock_qty","reorder_level","shipping_fee","eta_text","eta_days_min","eta_days_max","returnable","warranty_months"
        ]

        for pid in product_ids:
            skus = product_to_skus.get(pid, [])
            if not skus:
                continue
            stores_to_use = rng.randint(cfg.offers_per_product_min, cfg.offers_per_product_max)
            store_sample = rng.sample(store_ids, k=min(stores_to_use, len(store_ids)))

            for sku_id in skus:
                for sid in store_sample:
                    price, mrp, dpct = price_for_offer(rng)
                    stock = int(max(0, rng.gauss(40, 20)))
                    reorder = int(max(0, stock * 0.2))
                    ship_fee = 0 if rng.random() < 0.75 else rng.choice([29, 49, 99])
                    eta_min = rng.choice([1, 2, 3])
                    eta_max = eta_min + rng.choice([0, 1, 2])
                    eta_text = "Fast delivery" if eta_min <= 2 else "Arriving soon"
                    returnable = rng.random() < 0.7
                    warranty = None if rng.random() < 0.8 else rng.choice([3, 6, 12])

                    offer_rows.append((
                        sid, sku_id, True, "INR",
                        inr_money(price), inr_money(mrp) if mrp else None, dpct,
                        stock, reorder,
                        inr_money(ship_fee) if ship_fee is not None else None,
                        eta_text, eta_min, eta_max,
                        returnable, warranty
                    ))

        offer_ids = insert_many_returning_ids(conn, "store_offers", offer_cols, offer_rows, cfg.batch_size)

        # 9) promotions + promotion_targets
        promo_rows = [
            ("Limited time deal", "Save today", "DISCOUNT", 10, None, 1, now_utc(), now_utc() + dt.timedelta(days=30), True),
            ("₹100 coupon", "On orders above ₹999", "COUPON", None, 100.0, 1, now_utc(), now_utc() + dt.timedelta(days=30), True),
            ("Bank offer", "Extra 5% off", "BANK", 5, None, 1, now_utc(), now_utc() + dt.timedelta(days=20), True),
        ]
        promo_cols = ["title","subtitle","promo_type","discount_pct","discount_amount","min_qty","valid_from","valid_to","is_active"]
        promo_ids = insert_many_returning_ids(conn, "promotions", promo_cols, promo_rows, cfg.batch_size)
        promo_id_deal = promo_ids[0]

        # Attach deal to subset of offers
        promo_target_rows = []
        target_count = int(len(offer_ids) * cfg.pct_products_on_promo)
        if target_count > 0:
            for oid in rng.sample(offer_ids, k=min(target_count, len(offer_ids))):
                promo_target_rows.append((promo_id_deal, oid))
        insert_many(conn, "promotion_targets", ["promo_id","store_offer_id"], promo_target_rows, cfg.batch_size)

        # 10) Reviews + media + votes
        # Note: item_reviews has UNIQUE(product_id,user_id), so we must ensure distinct pairs.
        review_rows = []
        review_cols = ["product_id","sku_id","user_id","rating","title","body","is_verified_purchase"]
        used_pairs = set()

        # map sku list per product for sku_id assignment
        product_list = product_ids[:]  # to sample
        for _ in range(cfg.num_reviews):
            pid = rng.choice(product_list)
            uid = rng.choice(misc_user_ids)  # reviewers
            if (pid, uid) in used_pairs:
                continue
            used_pairs.add((pid, uid))
            sku_id = rng.choice(product_to_skus.get(pid, [None])) if rng.random() < 0.7 else None
            rating = pick_weighted(rng, [(5,0.45),(4,0.3),(3,0.15),(2,0.07),(1,0.03)])
            title = rng.choice(["Great", "Nice", "Value for money", "Not bad", "Loved it", "Okay"])
            body = rng.choice([
                "My pet loved it. Good quality and fast delivery.",
                "Seems durable. Using it daily.",
                "Packaging was good. Product matches description.",
                "Decent purchase for the price.",
                "Will buy again."
            ])
            verified = rng.random() < 0.4
            review_rows.append((pid, sku_id, uid, int(rating), title, body, verified))

        review_ids = insert_many_returning_ids(conn, "item_reviews", review_cols, review_rows, cfg.batch_size)

        # review_media
        review_media_rows = []
        for rid in review_ids:
            if rng.random() < cfg.review_media_pct:
                # 1-2 images
                for j in range(rng.randint(1, 2)):
                    review_media_rows.append((rid, "IMAGE", loremflickr_uri("dog,toy", lock=rid*10+j), j+1))
        insert_many(conn, "review_media", ["review_id","media_type","uri","sort_order"], review_media_rows, cfg.batch_size)

        # review_votes
        vote_rows = []
        vote_cols = ["review_id","user_id","is_helpful"]
        for _ in range(cfg.num_review_votes):
            rid = rng.choice(review_ids)
            uid = rng.choice(misc_user_ids)
            vote_rows.append((rid, uid, rng.random() < 0.75))
        # unique constraint(review_id,user_id) => de-dupe in memory
        vote_rows = list({(r,u): (r,u,h) for (r,u,h) in vote_rows}.values())
        insert_many(conn, "review_votes", vote_cols, vote_rows, cfg.batch_size)

        # 11) store reviews + votes
        store_review_rows = []
        store_review_cols = ["store_id","user_id","rating","title","body"]
        used_store_pairs = set()
        for _ in range(cfg.num_store_reviews):
            sid = rng.choice(store_ids)
            uid = rng.choice(parent_ids + misc_user_ids)
            if (sid, uid) in used_store_pairs:
                continue
            used_store_pairs.add((sid, uid))
            rating = pick_weighted(rng, [(5,0.4),(4,0.35),(3,0.15),(2,0.07),(1,0.03)])
            store_review_rows.append((sid, uid, int(rating), "Good seller", "Quick dispatch and helpful support."))
        store_review_ids = insert_many_returning_ids(conn, "store_reviews", store_review_cols, store_review_rows, cfg.batch_size)

        store_vote_rows = []
        for _ in range(cfg.num_store_review_votes):
            rid = rng.choice(store_review_ids)
            uid = rng.choice(parent_ids + misc_user_ids)
            store_vote_rows.append((rid, uid, rng.random() < 0.8))
        store_vote_rows = list({(r,u): (r,u,h) for (r,u,h) in store_vote_rows}.values())
        insert_many(conn, "store_review_votes", ["review_id","user_id","is_helpful"], store_vote_rows, cfg.batch_size)

        # 12) Q/A
        q_rows = []
        q_cols = ["product_id","user_id","question"]
        for _ in range(cfg.num_questions):
            pid = rng.choice(product_ids)
            uid = rng.choice(parent_ids)
            q_rows.append((pid, uid, rng.choice([
                "Is this suitable for puppies?",
                "How long does it last?",
                "Is it washable?",
                "Is it safe for cats?",
                "What is the size?"
            ])))
        q_ids = insert_many_returning_ids(conn, "item_questions", q_cols, q_rows, cfg.batch_size)

        a_rows = []
        a_cols = ["question_id","user_id","answer"]
        for _ in range(cfg.num_answers):
            qid = rng.choice(q_ids)
            uid = rng.choice(owner_ids)  # store owners answering
            a_rows.append((qid, uid, rng.choice([
                "Yes, suitable for supervised play.",
                "Washable and easy to maintain.",
                "Please refer to size chart images.",
                "Recommended for medium chewers."
            ])))
        insert_many(conn, "item_answers", a_cols, a_rows, cfg.batch_size)

        # 13) wishlists (parents) + few items
        wish_rows = [(uid,) for uid in parent_ids[: max(1, min(len(parent_ids), 200))]]
        wishlist_ids = insert_many_returning_ids(conn, "wishlists", ["user_id"], wish_rows, cfg.batch_size)
        wish_item_rows = []
        for wid in wishlist_ids:
            for pid in rng.sample(product_ids, k=min(10, len(product_ids))):
                wish_item_rows.append((wid, pid))
        insert_many(conn, "wishlist_items", ["wishlist_id","product_id"], wish_item_rows, cfg.batch_size)

        # 14) events (views/add_to_cart/wishlist/purchase)
        event_rows = []
        event_cols = ["user_id","product_id","event_type","meta"]
        for uid in parent_ids:
            for _ in range(cfg.events_per_user):
                pid = rng.choice(product_ids)
                etype = pick_weighted(rng, [("VIEW",0.7),("ADD_TO_CART",0.15),("WISHLIST",0.1),("PURCHASE",0.05)])
                meta = {"src": "seed", "ts": now_utc().isoformat()}
                event_rows.append((uid, pid, etype, json.dumps(meta)))
        insert_many(conn, "user_item_events", event_cols, event_rows, cfg.batch_size)

        # 15) relations (SIMILAR/ALSO_LIKE/FBT)
        rel_rows = []
        rel_cols = ["product_id","related_product_id","relation_type","weight"]
        for pid in product_ids[: min(cfg.num_products, 10000)]:  # cap relations generation for speed (configurable)
            related = rng.sample(product_ids, k=min(cfg.relations_per_product, len(product_ids)))
            for rid in related:
                if rid == pid:
                    continue
                rel_type = pick_weighted(rng, [("SIMILAR",0.55),("ALSO_LIKE",0.35),("FBT",0.10)])
                rel_rows.append((pid, rid, rel_type, rng.randint(50, 200)))
        # de-dupe by unique constraint
        rel_rows = list({(p,r,t): (p,r,t,w) for (p,r,t,w) in rel_rows}.values())
        insert_many(conn, "item_relations", rel_cols, rel_rows, cfg.batch_size)

        # 16) carts demo (optional)
        if cfg.create_demo_cart:
            cart_rows = [(uid, None) for uid in parent_ids[: min(50, len(parent_ids))]]
            cart_ids = insert_many_returning_ids(conn, "carts", ["parent_user_id","address_id"], cart_rows, cfg.batch_size)
            cart_item_rows = []
            # pick random offers for cart items
            for cid in cart_ids:
                for oid in rng.sample(offer_ids, k=min(5, len(offer_ids))):
                    cart_item_rows.append((cid, oid, rng.randint(1, 3)))
            insert_many(conn, "cart_items", ["cart_id","store_offer_id","qty"], cart_item_rows, cfg.batch_size)

        print("[seed] DONE ✅")
        print(f"  users: {len(user_ids)} (parents={len(parent_ids)} owners={len(owner_ids)} reviewers={len(misc_user_ids)})")
        print(f"  stores: {len(store_ids)}")
        print(f"  products: {len(product_ids)}")
        print(f"  skus: {sum(len(v) for v in product_to_skus.values())}")
        print(f"  offers: {len(offer_ids)}")
        print(f"  reviews: {len(review_ids)}")
        print(f"  events: {len(event_rows)}")
        print(f"  relations: {len(rel_rows)}")


# -----------------------------
# Content generators
# -----------------------------

def make_product_copy(rng: random.Random, cat: str, brand: str, i: int) -> Tuple[str, str, str, str | None]:
    # returns (title, short_desc, description, variant_theme)
    if cat == "FOOD":
        species = pick_weighted(rng, [("dog",0.65),("cat",0.35)])
        stage = pick_weighted(rng, [("Puppy/Kitten",0.25),("Adult",0.55),("Senior",0.20)])
        flavor = rng.choice(["Chicken", "Lamb", "Fish", "Ocean Fish", "Egg", "Beef", "Veg"])
        title = f"{brand} {stage} {flavor} Dry Food"
        short = f"{stage} nutrition. Balanced protein + vitamins. {species.title()} friendly."
        desc = f"{title}. Formulated for {species}s. Supports digestion, coat health, and immunity. Store sealed in a cool dry place."
        variant_theme = "Size"
        return title, short, desc, variant_theme

    if cat == "ACCESSORY":
        kind = rng.choice(["Squeaky Bone Toy", "Treat Ball Puzzle", "Nylon Leash", "No-Pull Harness", "Stainless Bowl", "Cat Scratcher", "Travel Carrier"])
        title = f"{brand} {kind}"
        short = rng.choice([
            "Durable and pet-safe. Great for daily use.",
            "Designed for comfort and easy cleaning.",
            "Helps reduce boredom. Suitable for supervised play."
        ])
        desc = f"{title}. {short} Ideal for dogs and cats depending on size. Replace if damaged."
        variant_theme = rng.choice([None, "Color", "Size"])
        return title, short, desc, variant_theme

    if cat == "MEDICINE":
        kind = rng.choice(["Tick & Flea Spray", "Anti-itch Shampoo", "Deworming Tablet", "Oral Rehydration Solution", "Skin Ointment"])
        title = f"{brand} {kind}"
        short = "External use where applicable. Follow label directions."
        desc = f"{title}. {short} Consult a vet if irritation occurs. Keep away from eyes and mouth."
        variant_theme = "Size"
        return title, short, desc, variant_theme

    # SERVICE
    title = f"{brand} Grooming Service"
    short = "Bath, nail trim, hygiene care. Appointment recommended."
    desc = f"{title}. Includes basic grooming depending on package. Please book a slot."
    variant_theme = "Package"
    return title, short, desc, variant_theme

def make_sku_variant(rng: random.Random, cat: str, variant_theme: str | None, idx: int) -> Tuple[str | None, str | None, str | None]:
    if not variant_theme:
        return None, None, "Standard"

    if variant_theme == "Size":
        pack = rng.choice(["500 g", "1 kg", "2 kg", "3 kg", "5 kg", "10 kg", "200 ml", "500 ml", "900 ml"])
        return "Size", pack, pack

    if variant_theme == "Color":
        color = rng.choice(["Yellow","Red","Blue","Green","Black"])
        return "Color", color, color

    if variant_theme == "Flavour":
        flav = rng.choice(["Chicken","Fish","Lamb","Beef"])
        return "Flavour", flav, flav

    if variant_theme == "Package":
        pack = rng.choice(["Basic", "Standard", "Premium"])
        return "Package", pack, pack

    return variant_theme, f"Var{idx+1}", f"Var{idx+1}"

def media_tag_for_category(cat: str) -> str:
    if cat == "FOOD":
        return "dog,petfood"
    if cat == "ACCESSORY":
        return "dog,toy"
    if cat == "MEDICINE":
        return "dog,medicine"
    return "dog,grooming"

def tags_for_product(rng: random.Random, cat: str, title: str) -> List[str]:
    base = []
    t = title.lower()
    if cat == "FOOD":
        base += ["food", "nutrition", "dry food"]
        if "puppy" in t or "kitten" in t:
            base += ["growth", "young"]
        if "cat" in t or "kitten" in t:
            base += ["cat food"]
        else:
            base += ["dog food"]
    elif cat == "ACCESSORY":
        base += ["accessory"]
        if "toy" in t or "ball" in t or "bone" in t:
            base += ["toy", "play", "chew"]
        if "leash" in t or "harness" in t:
            base += ["walk", "training"]
        if "bowl" in t:
            base += ["bowl", "feeding"]
    elif cat == "MEDICINE":
        base += ["hygiene", "care"]
        if "flea" in t or "tick" in t:
            base += ["tick control", "flea control"]
        if "shampoo" in t:
            base += ["shampoo", "skin care"]
    else:
        base += ["service", "grooming"]
    # add some random
    base += rng.sample(["premium","daily use","value pack","vet recommended","best seller","limited deal"], k=min(2, 6))
    # unique preserving order
    seen = set()
    out = []
    for x in base:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def specs_for_product(rng: random.Random, cat: str, title: str, variant_theme: str | None) -> List[Tuple[str,str,str,int]]:
    specs: List[Tuple[str,str,str,int]] = []
    if cat == "FOOD":
        specs += [
            ("Top highlights","Life stage", rng.choice(["Puppy/Kitten","Adult","Senior"]), 1),
            ("Top highlights","Form","Dry kibble", 2),
            ("Product details","Shelf life", rng.choice(["12 months","18 months","24 months"]), 10),
            ("Safety & care","Storage","Keep sealed; store in cool dry place", 20),
        ]
    elif cat == "ACCESSORY":
        specs += [
            ("Top highlights","Material", rng.choice(["Natural rubber","Nylon","Stainless steel","Fabric"]), 1),
            ("Top highlights","Ideal for", rng.choice(["Small pets","Medium chewers","All sizes"]), 2),
            ("Product details","Care", rng.choice(["Washable; air dry","Wipe clean"]), 10),
            ("Safety & care","Note","Supervise play. Replace if damaged.", 20),
        ]
    elif cat == "MEDICINE":
        specs += [
            ("Top highlights","Use", "External use (where applicable)", 1),
            ("Top highlights","Suitable for", rng.choice(["Dogs","Cats","Dogs & Cats"]), 2),
            ("Product details","Directions", "Follow label directions", 10),
            ("Safety & care","Warning","Avoid eyes/mouth. Consult vet if irritation.", 20),
        ]
    else:
        specs += [
            ("Top highlights","Service type", "Grooming", 1),
            ("Product details","Booking", "Appointment recommended", 10),
        ]
    # add a few extras
    for i in range(6):
        specs.append(("Product details", rng.choice(["Weight","Length","Width","Color","Package","Flavor"]), rng.choice(["Standard","Varies","As shown"]), 30+i))
    # de-dupe by (group,key,value)
    uniq = []
    seen = set()
    for g,k,v,so in specs:
        key = (g,k,v)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((g,k,v,so))
    return uniq

def price_for_offer(rng: random.Random) -> Tuple[float, float | None, int | None]:
    base = max(49, rng.gauss(499, 350))
    base = min(base, 9999)
    price = inr_money(base)
    if rng.random() < 0.6:
        mrp = inr_money(price * rng.uniform(1.05, 1.35))
        pct = int(round((mrp - price) * 100 / mrp))
        pct = max(1, min(95, pct))
        return price, mrp, pct
    return price, None, None


# -----------------------------
# CLI
# -----------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True, help="Postgres DSN e.g. postgresql://user:pass@localhost:5432/petcare")
    p.add_argument("--schema-file", default="schema.sql", help="Path to schema.sql (DROP+CREATE)")
    p.add_argument("--seed", type=int, default=42)

    p.add_argument("--parents", type=int, default=2000)
    p.add_argument("--store-owners", type=int, default=300)
    p.add_argument("--stores", type=int, default=100)
    p.add_argument("--brands", type=int, default=30)
    p.add_argument("--products", type=int, default=50000)

    p.add_argument("--min-skus", type=int, default=1)
    p.add_argument("--max-skus", type=int, default=4)

    p.add_argument("--media-per-product", type=int, default=3)
    p.add_argument("--specs-per-product", type=int, default=10)
    p.add_argument("--tags-per-product", type=int, default=5)

    p.add_argument("--offers-min", type=int, default=1)
    p.add_argument("--offers-max", type=int, default=2)
    p.add_argument("--promo-pct", type=float, default=0.12, help="fraction of offers to attach a promo to (0..1)")

    p.add_argument("--reviews", type=int, default=1000)
    p.add_argument("--review-media-pct", type=float, default=0.15)
    p.add_argument("--review-votes", type=int, default=4000)

    p.add_argument("--store-reviews", type=int, default=800)
    p.add_argument("--store-review-votes", type=int, default=2000)

    p.add_argument("--questions", type=int, default=800)
    p.add_argument("--answers", type=int, default=500)

    p.add_argument("--relations-per-product", type=int, default=6)
    p.add_argument("--events-per-user", type=int, default=20)

    p.add_argument("--batch-size", type=int, default=5000)
    p.add_argument("--demo-cart", action="store_true")

    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = build_config(args)

    if not os.path.exists(cfg.schema_file):
        print(f"ERROR: schema file not found: {cfg.schema_file}", file=sys.stderr)
        sys.exit(1)

    seed_all(args.dsn, cfg)
