# scripts/gen/config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class SeedConfig:
    # -------------------------
    # core
    # -------------------------
    rng_seed: int = 1337
    batch_size: int = 5000

    # -------------------------
    # commerce sizes
    # -------------------------
    num_users: int = 300
    num_store_owners: int = 120
    num_stores: int = 100
    num_products: int = 50_000

    avg_skus_per_product: float = 1.4
    offers_per_sku: float = 1.05

    # reviews/events
    num_reviews: int = 1_000
    reviews_mode: str = "sparse"          # sparse | dense
    reviews_per_product: int = 50         # used if dense
    min_reviews_per_product_for_dense: int = 10  # dense mode lower bound

    events_per_user: int = 30
    num_events: int = 20_000

    # promotions
    num_promotions: int = 120
    promo_attach_rate: float = 0.12
    max_promos_per_offer: int = 2
    promo_duration_days: int = 30

    promo_discount_pct_min: int = 5
    promo_discount_pct_max: int = 25

    promo_bank_pct_min: int = 3
    promo_bank_pct_max: int = 15

    coupon_amounts: Tuple[int, ...] = (50, 100, 150, 200)
    promo_type_weights: Tuple[float, float, float, float] = (0.70, 0.20, 0.07, 0.03)  # DISCOUNT, COUPON, BANK, BUNDLE
    promo_attach_two_prob: float = 0.20

    # relations
    relations_coverage_pct: float = 0.25
    similar_per_product: int = 8
    also_like_per_product: int = 6
    fbt_per_product: int = 3

    # carts
    demo_cart: bool = False
    demo_cart_users: int = 50
    demo_cart_items_per_user: int = 10
    demo_cart_min_qty: int = 1
    demo_cart_max_qty: int = 3

    # orders (IMPORTANT for UI: delivered + in-progress)
    demo_orders: bool = True
    demo_orders_users: int = 200
    delivered_orders_per_user: int = 1
    inprogress_orders_per_user: int = 1
    order_items_min: int = 1
    order_items_max: int = 4

    # -------------------------
    # mandatory vet + parent flow
    # -------------------------
    num_vets: int = 50
    num_parents: int = 500
    pets_per_parent: int = 2  # force >=2 in seeder

    # slots/appointments
    locations_per_vet: int = 1
    slot_minutes: int = 2                # ✅ user asked smaller slots
    appointment_span_days: int = 30      # range to schedule into future/past
    appointments_per_parent: int = 6     # 2 upcoming + 2 completed + rest mixed

    # appointment state mix
    pct_booked: float = 0.55
    pct_completed: float = 0.25
    pct_cancelled: float = 0.10
    pct_in_consult: float = 0.05
    pct_no_show: float = 0.05

    # consults
    pct_consult_for_completed: float = 0.90
    max_consults: int = 50_000

    # vaccines
    pct_pets_with_vaccine_plan: float = 0.90
    pct_pets_with_vaccine_records: float = 0.70
    pct_plan_items_completed: float = 0.35   # ensures some “completed” in UI

    # compatibility aliases used by older modules
    @property
    def users(self) -> int: return self.num_users

    @property
    def stores(self) -> int: return self.num_stores

    @property
    def products(self) -> int: return self.num_products

    @property
    def reviews(self) -> int: return self.num_reviews
