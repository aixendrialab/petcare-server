from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal, Any, List

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()
ProviderRole = Literal["vendor","pharmacist","nutritionist","hostel"]

async def _my_store_id(user_id: int, role: str) -> int:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM provider_stores WHERE owner_user_id=%s AND role=%s", (user_id, role))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(400, f"No store profile for role={role}. Complete onboarding first.")
        return int(row[0])

# --------------------------
# Provider catalog = offers list
# --------------------------

@router.get("/store/items")
async def list_my_items(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
              so.id AS offer_id,
              so.store_id,
              p.id AS product_id,
              sku.id AS sku_id,
              p.category,
              p.title,
              COALESCE(b.name, p.brand_text) AS brand,
              so.price, so.mrp, so.currency, so.discount_pct,
              so.stock_qty, so.reorder_level,
              so.is_active,
              so.shipping_fee, so.eta_text, so.eta_days_min, so.eta_days_max, so.returnable, so.warranty_months
            FROM store_offers so
            JOIN catalog_skus sku ON sku.id = so.sku_id
            JOIN catalog_products p ON p.id = sku.product_id
            LEFT JOIN brands b ON b.id = p.brand_id
            WHERE so.store_id=%s
            ORDER BY p.title, sku.sort_order, so.id DESC
            """,
            (store_id,),
        )
        rows = await cur.fetchall()

    keys = [
        "offer_id","store_id","product_id","sku_id","category","title","brand",
        "price","mrp","currency","discount_pct",
        "stock_qty","reorder_level",
        "is_active",
        "shipping_fee","eta_text","eta_days_min","eta_days_max","returnable","warranty_months"
    ]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class OfferUpsertIn(BaseModel):
    offer_id: Optional[int] = None  # update by offer_id
    sku_id: Optional[int] = None    # create/update by sku_id (must already exist)

    price: Optional[float] = None
    mrp: Optional[float] = None
    discount_pct: Optional[int] = None
    stock_qty: Optional[int] = None
    reorder_level: Optional[int] = None
    is_active: Optional[bool] = None

    shipping_fee: Optional[float] = None
    eta_text: Optional[str] = None
    eta_days_min: Optional[int] = None
    eta_days_max: Optional[int] = None
    returnable: Optional[bool] = None
    warranty_months: Optional[int] = None

@router.post("/store/items")
async def upsert_offer(role: ProviderRole = Query(...), body: OfferUpsertIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)

    if not body:
        raise HTTPException(400, "Body required")

    async with get_conn() as conn, conn.cursor() as cur:
        if body.offer_id:
            # update existing offer
            await cur.execute(
                """
                UPDATE store_offers SET
                  price=COALESCE(%s, price),
                  mrp=COALESCE(%s, mrp),
                  discount_pct=COALESCE(%s, discount_pct),
                  stock_qty=COALESCE(%s, stock_qty),
                  reorder_level=COALESCE(%s, reorder_level),
                  is_active=COALESCE(%s, is_active),
                  shipping_fee=COALESCE(%s, shipping_fee),
                  eta_text=COALESCE(%s, eta_text),
                  eta_days_min=COALESCE(%s, eta_days_min),
                  eta_days_max=COALESCE(%s, eta_days_max),
                  returnable=COALESCE(%s, returnable),
                  warranty_months=COALESCE(%s, warranty_months),
                  updated_at=now()
                WHERE id=%s AND store_id=%s
                RETURNING id
                """,
                (
                    body.price, body.mrp, body.discount_pct,
                    body.stock_qty, body.reorder_level, body.is_active,
                    body.shipping_fee, body.eta_text, body.eta_days_min, body.eta_days_max,
                    body.returnable, body.warranty_months,
                    body.offer_id, store_id,
                ),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "Offer not found")
            return {"ok": True, "offer_id": int(row[0])}

        # create offer requires sku_id
        if not body.sku_id:
            raise HTTPException(400, "sku_id is required to create an offer")

        await cur.execute("SELECT id FROM catalog_skus WHERE id=%s", (body.sku_id,))
        if not await cur.fetchone():
            raise HTTPException(400, "Invalid sku_id")

        await cur.execute(
            """
            INSERT INTO store_offers
              (store_id, sku_id, is_active, price, mrp, discount_pct, stock_qty, reorder_level,
               shipping_fee, eta_text, eta_days_min, eta_days_max, returnable, warranty_months)
            VALUES
              (%s,%s,COALESCE(%s,TRUE),COALESCE(%s,0),%s,%s,COALESCE(%s,0),COALESCE(%s,0),
               %s,%s,%s,%s,%s,%s)
            ON CONFLICT (store_id, sku_id) DO UPDATE SET
              is_active=COALESCE(EXCLUDED.is_active, store_offers.is_active),
              price=COALESCE(EXCLUDED.price, store_offers.price),
              mrp=COALESCE(EXCLUDED.mrp, store_offers.mrp),
              discount_pct=COALESCE(EXCLUDED.discount_pct, store_offers.discount_pct),
              stock_qty=COALESCE(EXCLUDED.stock_qty, store_offers.stock_qty),
              reorder_level=COALESCE(EXCLUDED.reorder_level, store_offers.reorder_level),
              shipping_fee=COALESCE(EXCLUDED.shipping_fee, store_offers.shipping_fee),
              eta_text=COALESCE(EXCLUDED.eta_text, store_offers.eta_text),
              eta_days_min=COALESCE(EXCLUDED.eta_days_min, store_offers.eta_days_min),
              eta_days_max=COALESCE(EXCLUDED.eta_days_max, store_offers.eta_days_max),
              returnable=COALESCE(EXCLUDED.returnable, store_offers.returnable),
              warranty_months=COALESCE(EXCLUDED.warranty_months, store_offers.warranty_months),
              updated_at=now()
            RETURNING id
            """,
            (
                store_id, body.sku_id,
                body.is_active, body.price, body.mrp, body.discount_pct,
                body.stock_qty, body.reorder_level,
                body.shipping_fee, body.eta_text, body.eta_days_min, body.eta_days_max,
                body.returnable, body.warranty_months,
            ),
        )
        oid = int((await cur.fetchone())[0])
        return {"ok": True, "offer_id": oid}

# --------------------------
# Provider inventory (v2)
# --------------------------

@router.get("/store/inventory")
async def list_inventory(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
              so.id          AS offer_id,
              so.store_id,
              p.id           AS product_id,
              sku.id         AS sku_id,
              p.title,
              CASE
                WHEN sku.variant_key IS NOT NULL AND sku.variant_value IS NOT NULL
                  THEN (sku.variant_key || ': ' || sku.variant_value)
                ELSE NULL
              END AS variant,
              so.stock_qty,
              so.reorder_level,
              so.price,
              so.mrp,
              so.currency,
              so.is_active
            FROM store_offers so
            JOIN catalog_skus sku ON sku.id = so.sku_id
            JOIN catalog_products p ON p.id = sku.product_id
            WHERE so.store_id=%s
            ORDER BY p.title, sku.sort_order, so.id
            """,
            (store_id,),
        )
        rows = await cur.fetchall()

    keys = [
        "offer_id","store_id","product_id","sku_id","title","variant",
        "stock_qty","reorder_level","price","mrp","currency","is_active"
    ]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class AdjustStockIn(BaseModel):
    sku_id: int
    delta: int
    reorder_level: Optional[int] = None

@router.post("/store/inventory/adjust")
async def adjust_stock(role: ProviderRole = Query(...), body: AdjustStockIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM store_offers WHERE store_id=%s AND sku_id=%s",
            (store_id, body.sku_id),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Offer not found for this SKU in your store")
        offer_id = int(row[0])

        await cur.execute(
            """
            UPDATE store_offers SET
              stock_qty = GREATEST(stock_qty + %s, 0),
              reorder_level = COALESCE(%s, reorder_level),
              updated_at=now()
            WHERE id=%s AND store_id=%s
            RETURNING id, stock_qty
            """,
            (body.delta, body.reorder_level, offer_id, store_id),
        )
        oid, qty = await cur.fetchone()

    return {"ok": True, "offer_id": oid, "stock_qty": qty}
