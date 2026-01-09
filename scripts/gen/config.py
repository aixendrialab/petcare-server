# scripts/gen/config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class SeedConfig:
    # -------------------------
    # Core sizes
    # -------------------------
    rng_seed: int = 1337
    batch_size: int = 5000

    num_users: int = 300
    num_store_owners: int = 120
    num_stores: int = 100
    num_products: int = 50_000

    # SKUs
    avg_skus_per_product: float = 1.4  # ~40% have 2 skus

    # Offers
    offers_per_sku: float = 1.05       # avg store_offers per sku

    # Reviews / events / relations
    num_reviews: int = 1_000
    num_events: int = 20_000

    relations_coverage_pct: float = 0.25
    similar_per_product: int = 8
    also_like_per_product: int = 6
    fbt_per_product: int = 3

    # -------------------------
    # Promotions
    # -------------------------
    num_promotions: int = 120
    promo_attach_rate: float = 0.12          # fraction of offers that get promos
    max_promos_per_offer: int = 2
    promo_attach_two_prob: float = 0.20      # of attached offers, chance to attach 2
    promo_duration_days: int = 30

    promo_discount_pct_min: int = 5
    promo_discount_pct_max: int = 25

    promo_bank_pct_min: int = 3
    promo_bank_pct_max: int = 15

    coupon_amounts: Tuple[int, ...] = (50, 100, 150, 200)

    # order: DISCOUNT, COUPON, BANK, BUNDLE
    promo_type_weights: Tuple[float, float, float, float] = (0.70, 0.20, 0.07, 0.03)

    # -------------------------
    # Reviews strategy knobs
    # -------------------------
    # If you want "every product has >= 50 reviews", set:
    #   reviews_mode="dense" and reviews_per_product=50
    reviews_mode: str = "sparse"      # "sparse" | "dense"
    reviews_per_product: int = 50     # used when reviews_mode="dense"
    reviews_verified_rate: float = 0.40
    reviews_media_rate: float = 0.10
    review_votes_rate: float = 0.30   # fraction of reviews that get votes

    # -------------------------
    # Demo cart knobs
    # -------------------------
    demo_cart: bool = False
    demo_cart_users: int = 50               # how many users get carts pre-filled
    demo_cart_items_per_user: int = 10      # items per cart
    demo_cart_max_distinct_stores: int = 4  # keep carts realistic

    # Optional for future
    seed_vet: bool = False

    # -------------------------
    # Compatibility aliases
    # -------------------------
    @property
    def users(self) -> int:
        return self.num_users

    @property
    def stores(self) -> int:
        return self.num_stores

    @property
    def products(self) -> int:
        return self.num_products

    @property
    def reviews(self) -> int:
        return self.num_reviews

    # Some modules want events_per_user; main.py can set this dynamically
    events_per_user: int = 30
