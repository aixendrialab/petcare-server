# scripts/gen/orders.py
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
from scripts.gen.specials import SPECIAL_USERS


SPECIAL_PARENT_PHONES = [p for (p, _n, _e, roles) in SPECIAL_USERS if "parent" in roles]


def _resolve_user_ids_by_phone(conn, phones: List[str]) -> List[int]:
    if not phones:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE phone = ANY(%s)", (phones,))
        return [int(r[0]) for r in cur.fetchall()]


def _ensure_default_address(conn, user_id: int) -> int:
    """
    Orders require address_id NOT NULL.
    If user has none, create one.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM user_addresses WHERE user_id=%s ORDER BY is_default DESC, id ASC LIMIT 1",
            (user_id,),
        )
        r = cur.fetchone()
        if r:
            return int(r[0])

        cur.execute(
            """
            INSERT INTO user_addresses
              (user_id, label, recipient, phone, line1, line2, landmark, city, state, pincode, is_default)
            VALUES
              (%s,'Home','Seed User',NULL,'Seed Street','',NULL,'Vizag','AP','530001',TRUE)
            RETURNING id
            """,
            (user_id,),
        )
        return int(cur.fetchone()[0])


def _offer_payloads_for_order(conn, offer_ids: List[int], pick: List[int]) -> List[Tuple]:
    """
    For each offer_id return:
      store_offer_id, store_id, sku_id, product_id, price, mrp, currency, discount_pct, gst_pct, title, variant
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              so.id,
              so.store_id,
              so.sku_id,
              p.id as product_id,
              so.price::float,
              COALESCE(so.mrp, NULL),
              so.currency,
              so.discount_pct,
              COALESCE(tc.gst_pct, 0)::float AS gst_pct,
              p.title,
              COALESCE(sku.pack_label, (sku.variant_key || ':' || sku.variant_value)) as variant
            FROM store_offers so
            JOIN catalog_skus sku ON sku.id = so.sku_id
            JOIN catalog_products p ON p.id = sku.product_id
            LEFT JOIN tax_classes tc ON tc.code = p.tax_class
            WHERE so.id = ANY(%s)
            """,
            (pick,),
        )
        return cur.fetchall()


def seed_demo_orders(conn, parent_user_ids: List[int], offer_ids: List[int], cfg) -> None:
    """
    Creates orders so Orders screen is never empty.
    - chooses cfg.demo_orders_users random parents
    - always includes special parents
    - per user: delivered + in-progress counts
    - for special users: richer (more orders + more items)
    """
    if not offer_ids:
        print("[seed_orders] skipped: no offers")
        return

    rng = random.Random(cfg.rng_seed + 310)

    base_users = min(int(cfg.demo_orders_users), len(parent_user_ids))
    picked = rng.sample(parent_user_ids, k=base_users) if base_users > 0 else []

    special_ids = _resolve_user_ids_by_phone(conn, SPECIAL_PARENT_PHONES)
    for sid in special_ids:
        if sid not in picked:
            picked.append(sid)

    delivered_per = max(0, int(cfg.delivered_orders_per_user))
    inprog_per = max(0, int(cfg.inprogress_orders_per_user))

    # Rich demo overrides for specials
    rich_delivered = 2
    rich_inprog = 2
    rich_items_min = 3
    rich_items_max = 6

    items_min = max(1, int(cfg.order_items_min))
    items_max = max(items_min, int(cfg.order_items_max))

    now = datetime.now(tz=timezone.utc)

    # We need stores list for store_id on orders
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM provider_stores WHERE status='ACTIVE' ORDER BY id")
        store_ids = [int(r[0]) for r in cur.fetchall()]

    if not store_ids:
        print("[seed_orders] skipped: no stores")
        return

    # helper to create one order
    def create_order_for_user(user_id: int, status: str, item_count: int) -> None:
        address_id = _ensure_default_address(conn, user_id)

        # pick offers, potentially from multiple stores; but schema has 1 order per store
        picks = rng.sample(offer_ids, k=min(item_count, len(offer_ids)))
        offer_rows = _offer_payloads_for_order(conn, offer_ids, picks)

        # group by store_id
        by_store: Dict[int, List[Tuple]] = {}
        for row in offer_rows:
            so_id, store_id, sku_id, product_id, price, mrp, currency, dpct, gst_pct, title, variant = row
            by_store.setdefault(int(store_id), []).append(row)

        with conn.cursor() as cur:
            for store_id, rows in by_store.items():
                # create order header
                created_at = now - timedelta(days=rng.randint(1, 30)) if status == "DELIVERED" else now - timedelta(hours=rng.randint(1, 48))
                cur.execute(
                    """
                    INSERT INTO orders
                      (parent_user_id, store_id, address_id, status, created_at, currency,
                       items_total, discount_total, shipping_fee, tax_total, grand_total)
                    VALUES
                      (%s,%s,%s,%s,%s,%s,0,0,0,0,0)
                    RETURNING id
                    """,
                    (user_id, store_id, address_id, status, created_at, "INR"),
                )
                order_id = int(cur.fetchone()[0])

                items_total = 0.0
                discount_total = 0.0
                tax_total = 0.0
                shipping_fee = 0.0

                for (so_id, _sid, sku_id, product_id, price, mrp, currency, dpct, gst_pct, title, variant) in rows:
                    qty = rng.randint(1, 2)
                    unit_price = float(price)
                    line = unit_price * qty
                    items_total += line

                    disc_amt = 0.0
                    if mrp is not None and float(mrp) > unit_price:
                        disc_amt = (float(mrp) - unit_price) * qty
                        discount_total += disc_amt

                    gst_amt = (line * float(gst_pct) / 100.0)
                    tax_total += gst_amt

                    cur.execute(
                        """
                        INSERT INTO order_items
                          (order_id, store_offer_id, sku_id, product_id,
                           title_snapshot, variant_snapshot, qty,
                           unit_price, mrp, discount_amt, gst_pct, gst_amt, line_total)
                        VALUES
                          (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            order_id, int(so_id), int(sku_id), int(product_id),
                            str(title), str(variant) if variant else None, qty,
                            unit_price, float(mrp) if mrp is not None else None,
                            disc_amt, float(gst_pct), gst_amt, line
                        ),
                    )

                grand_total = items_total - discount_total + shipping_fee + tax_total
                cur.execute(
                    """
                    UPDATE orders SET
                      items_total=%s,
                      discount_total=%s,
                      shipping_fee=%s,
                      tax_total=%s,
                      grand_total=%s
                    WHERE id=%s
                    """,
                    (items_total, discount_total, shipping_fee, tax_total, grand_total, order_id),
                )

    # Create orders
    for uid in picked:
        is_special = uid in special_ids

        dcount = rich_delivered if is_special else delivered_per
        icount = rich_inprog if is_special else inprog_per

        for _ in range(dcount):
            create_order_for_user(uid, "DELIVERED", rng.randint(rich_items_min, rich_items_max) if is_special else rng.randint(items_min, items_max))
        for _ in range(icount):
            status = rng.choice(["CONFIRMED", "PACKED", "DISPATCHED"])
            create_order_for_user(uid, status, rng.randint(rich_items_min, rich_items_max) if is_special else rng.randint(items_min, items_max))

    print(f"[seed_orders] users={len(picked)} (includes special) delivered/user={delivered_per} inprog/user={inprog_per} (special boosted)")
