from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict

# =========================================================
# Enums / literals (match schema v2)
# =========================================================

Category = Literal["FOOD", "ACCESSORY", "MEDICINE", "SERVICE"]
Currency = Literal["INR"]

ProviderRole = Literal["vendor", "pharmacist", "nutritionist", "hostel"]
MediaType = Literal["IMAGE", "VIDEO"]

PromoType = Literal["DISCOUNT", "COUPON", "BANK", "BUNDLE"]
RelationType = Literal["SIMILAR", "ALSO_LIKE", "FBT"]

EventType = Literal["VIEW", "ADD_TO_CART", "WISHLIST", "PURCHASE"]

# =========================================================
# Common primitives
# =========================================================

class Money(BaseModel):
    amount: float
    currency: Currency = "INR"

class TaxInfo(BaseModel):
    code: Optional[str] = None       # e.g. GST_18
    gst_pct: Optional[float] = None  # e.g. 18.0
    hsn_code: Optional[str] = None

# =========================================================
# Address
# =========================================================

class Address(BaseModel):
    id: int
    label: Optional[str] = None
    recipient: str
    phone: Optional[str] = None

    line1: str
    line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    pincode: str

    lat: Optional[float] = None
    lng: Optional[float] = None

    is_default: bool = False

# =========================================================
# Store (seller)
# =========================================================

class StoreBadge(BaseModel):
    badge: str

class StoreSummary(BaseModel):
    id: int
    role: ProviderRole
    display_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None

    logo_uri: Optional[str] = None
    about: Optional[str] = None

    rating_avg: Optional[float] = None
    rating_count: Optional[int] = None
    orders_30d: Optional[int] = None

    badges: List[str] = Field(default_factory=list)

class FulfillmentPromise(BaseModel):
    shipping_fee: Optional[Money] = None

    eta_text: Optional[str] = None
    eta_days_min: Optional[int] = None
    eta_days_max: Optional[int] = None

    returnable: Optional[bool] = None
    warranty_months: Optional[int] = None

    in_stock: Optional[bool] = None

# =========================================================
# Brand
# =========================================================

class BrandSummary(BaseModel):
    id: int
    name: str
    about: Optional[str] = None
    logo_uri: Optional[str] = None
    website: Optional[str] = None

# =========================================================
# Product + SKU (variant)
# =========================================================

class ProductMedia(BaseModel):
    uri: str
    media_type: MediaType = "IMAGE"
    label: Optional[str] = None
    sort_order: int = 0

class ProductSpec(BaseModel):
    spec_group: str = "General"  # "Top highlights", "Product details", ...
    key: str
    value: str
    sort_order: int = 0

class SkuOption(BaseModel):
    sku_id: int
    variant_key: Optional[str] = None
    variant_value: Optional[str] = None
    pack_label: Optional[str] = None
    sku_code: Optional[str] = None

    # optional: useful for quick variant switching
    best_offer_id: Optional[int] = None
    best_price: Optional[Money] = None
    in_stock: Optional[bool] = None

class Promotion(BaseModel):
    id: int
    title: str
    subtitle: Optional[str] = None
    promo_type: PromoType
    discount_pct: Optional[int] = None
    discount_amount: Optional[Money] = None
    min_qty: int = 1

class OfferCard(BaseModel):
    """
    A store selling a SKU. This is what drives 'Buy now' / price / stock.
    Backed by store_offers + joined store + promo targets.
    """
    offer_id: int
    store: StoreSummary
    sku: SkuOption

    price: Money
    mrp: Optional[Money] = None
    discount_pct: Optional[int] = None

    stock_qty: int = 0

    fulfillment: Optional[FulfillmentPromise] = None
    promotions: List[Promotion] = Field(default_factory=list)

# =========================================================
# Reviews
# =========================================================

class ReviewMedia(BaseModel):
    uri: str
    media_type: MediaType = "IMAGE"
    sort_order: int = 0

class ReviewVoteSummary(BaseModel):
    helpful: int = 0
    not_helpful: int = 0
    my_vote: Optional[bool] = None  # true/false if the current user voted

class ReviewPreview(BaseModel):
    id: int
    user_display: str
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    body: str
    created_at: str
    is_verified_purchase: bool = False

    media: List[ReviewMedia] = Field(default_factory=list)
    votes: ReviewVoteSummary = Field(default_factory=ReviewVoteSummary)

class ReviewSummary(BaseModel):
    rating_avg: float = 0.0
    rating_count: int = 0
    breakdown: Optional[List[Dict[str, float]]] = None  # optional later

# =========================================================
# Q/A
# =========================================================

class QuestionAnswer(BaseModel):
    question_id: int
    question: str
    asked_by: str
    asked_at: str

    answer_id: Optional[int] = None
    answer: Optional[str] = None
    answered_by: Optional[str] = None
    answered_at: Optional[str] = None

# =========================================================
# Product cards (for list/home)
# =========================================================

class ProductCard(BaseModel):
    product_id: int
    category: Category
    title: str
    brand: Optional[str] = None

    primary_image: Optional[str] = None

    best_price: Optional[Money] = None
    mrp: Optional[Money] = None
    discount_pct: Optional[int] = None

    rating_avg: Optional[float] = None
    rating_count: Optional[int] = None

    badges: List[str] = Field(default_factory=list)  # e.g. "Limited time deal"
    tags: List[str] = Field(default_factory=list)

# =========================================================
# Cross-sell / recommendations blocks
# =========================================================

class ProductBlock(BaseModel):
    title: str
    items: List[ProductCard] = Field(default_factory=list)

# =========================================================
# Product Detail (Amazon-like)
# =========================================================

class ProductDetail(BaseModel):
    product_id: int
    category: Category

    title: str
    brand: Optional[BrandSummary] = None
    brand_text: Optional[str] = None

    short_desc: Optional[str] = None
    description: Optional[str] = None

    tax: Optional[TaxInfo] = None
    prescription_required: bool = False

    media: List[ProductMedia] = Field(default_factory=list)
    specs: List[ProductSpec] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # Variants
    variant_theme: Optional[str] = None
    skus: List[SkuOption] = Field(default_factory=list)

    # Buying options (multiple sellers)
    offers: List[OfferCard] = Field(default_factory=list)

    # Social proof
    review_summary: ReviewSummary = Field(default_factory=ReviewSummary)
    review_previews: List[ReviewPreview] = Field(default_factory=list)
    bought_recently_label: Optional[str] = None  # derived from orders/events

    # Q/A
    qa: List[QuestionAnswer] = Field(default_factory=list)

    # Blocks
    frequently_bought_together: Optional[ProductBlock] = None
    similar_products: Optional[ProductBlock] = None
    more_to_explore: Optional[ProductBlock] = None
    top_deals: Optional[ProductBlock] = None

# =========================================================
# Shop Home
# =========================================================

class ShopHomeSectionCta(BaseModel):
    title: str
    route: str

class ShopHomeSection(BaseModel):
    key: str
    title: str
    subtitle: Optional[str] = None
    items: List[ProductCard] = Field(default_factory=list)
    cta: Optional[ShopHomeSectionCta] = None

class ShopHome(BaseModel):
    deliver_to_text: Optional[str] = None
    sections: List[ShopHomeSection] = Field(default_factory=list)

# =========================================================
# Cart
# =========================================================

class CartItem(BaseModel):
    offer_id: int
    product_id: int
    sku_id: int
    title: str
    variant: Optional[str] = None

    qty: int
    unit_price: Money
    line_total: Money

    store: StoreSummary
    primary_image: Optional[str] = None

class CartSummary(BaseModel):
    items: List[CartItem] = Field(default_factory=list)
    items_total: Money
    discount_total: Money
    shipping_fee: Money
    tax_total: Money
    grand_total: Money

    address: Optional[Address] = None

# =========================================================
# Events (optional API)
# =========================================================

class TrackEventRequest(BaseModel):
    product_id: int
    event_type: EventType
    meta: Dict = Field(default_factory=dict)
