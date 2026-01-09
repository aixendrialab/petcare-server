# scripts/gen/reset.py
from __future__ import annotations

def truncate_all(conn) -> None:
    """
    Truncate all tables we seed. CASCADE handles FK order.
    """
    tables = [
        # vet/parent domain
        "consult_medication",
        "consult_vitals",
        "consult",
        "appointments",
        "slot_overrides",
        "slot_settings",
        "vet_locations",
        "vet_profiles",
        "vaccination_intent",
        "pet_vaccine_plan_item",
        "pet_vaccine_plan",
        "vaccination_record",
        "vaccine_rule",
        "vaccine_catalog",
        "pets",

        # commerce
        "review_votes",
        "review_media",
        "item_reviews",
        "store_review_votes",
        "store_reviews",
        "item_answers",
        "item_questions",
        "wishlist_items",
        "wishlists",
        "user_item_events",
        "item_relations",
        "promotion_targets",
        "promotions",
        "order_items",
        "orders",
        "cart_items",
        "carts",
        "store_offers",
        "product_tags",
        "product_specs",
        "product_media",
        "catalog_skus",
        "catalog_products",
        "tax_classes",
        "brands",
        "store_badges",
        "provider_stores",
        "user_addresses",

        # users last
        "user_roles",
        "users",
    ]

    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.users')")
        if cur.fetchone()[0] is None:
            print("[seed] truncate_all skipped: schema not installed")
            return

    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE;")
