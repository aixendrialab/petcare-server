from pydantic import BaseModel, Field
from typing import Literal, Optional, List

Currency = Literal["INR"]

class StoreOfferOut(BaseModel):
    offer_id: int
    store_id: int
    product_id: int
    sku_id: int
    category: str
    title: str
    brand: Optional[str] = None

    price: float
    mrp: Optional[float] = None
    currency: str
    discount_pct: Optional[int] = None

    stock_qty: int
    reorder_level: int
    is_active: bool

    shipping_fee: Optional[float] = None
    eta_text: Optional[str] = None
    eta_days_min: Optional[int] = None
    eta_days_max: Optional[int] = None
    returnable: Optional[bool] = None
    warranty_months: Optional[int] = None

class StoreOfferListOut(BaseModel):
    items: List[StoreOfferOut]

class StoreInventoryOut(BaseModel):
    offer_id: int
    store_id: int
    product_id: int
    sku_id: int
    title: str
    variant: Optional[str] = None
    stock_qty: int
    reorder_level: int
    price: float
    mrp: Optional[float] = None
    currency: str
    is_active: bool

class StoreInventoryListOut(BaseModel):
    items: List[StoreInventoryOut]

class AdjustStockOut(BaseModel):
    ok: bool = True
    offer_id: int
    stock_qty: int

class StoreInventoryRow(BaseModel):
    offer_id: Optional[int] = None
    store_id: int

    product_id: int
    sku_id: Optional[int] = None

    category: str
    title: str
    brand: Optional[str] = None
    variant: Optional[str] = None

    stock_qty: int = 0
    reorder_level: int = 0

    price: float = 0
    mrp: Optional[float] = None
    currency: str = "INR"

    is_active: bool = False

class StoreInventoryListOut(BaseModel):
    items: List[StoreInventoryRow] = Field(default_factory=list)

class AdjustStockOut(BaseModel):
    ok: bool = True
    offer_id: int
    sku_id: int
    stock_qty: int