# scripts/gen/reset.py
from __future__ import annotations

# Keep list in dependency-safe order (children first)
TRUNCATE_TABLES = [
    "promotion_targets",
    "promotions",
    "review_votes",
    "review_media",
    "item_reviews",
    "user_item_events",
    "item_relations",
    "wishlist_items",
    "wishlists",
    "item_answers",
    "item_questions",
    "order_items",
    "orders",
    "cart_items",
    "carts",
    "store_offers",
    "catalog_skus",
    "product_tags",
    "product_specs",
    "product_media",
    "catalog_products",
    "store_badges",
    "provider_stores",
    "user_addresses",
    "brands",
    "tax_classes",
]

def truncate_all(conn) -> None:
    with conn.cursor() as cur:
        for t in TRUNCATE_TABLES:
            cur.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE;")
