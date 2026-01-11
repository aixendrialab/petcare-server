from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal, List

from app.api.models.store import AdjustStockOut, StoreInventoryListOut, StoreOfferListOut  # ✅ StoreOfferListOut removed
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()
ProviderRole = Literal["vendor", "pharmacist", "nutritionist", "hostel"]


# --------------------------
# Store resolution helpers
# --------------------------

async def _my_store_id(user_id: int, role: str) -> int:
    """Backward-compatible: returns latest store for this user+role."""
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM provider_stores WHERE owner_user_id=%s AND role=%s ORDER BY id DESC LIMIT 1",
            (user_id, role),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(400, f"No store profile for role={role}. Complete onboarding first.")
        return int(row[0])

async def _require_store_id(user_id: int, role: str, store_id: Optional[int]) -> int:
    """
    Multi-store safe:
    - If store_id provided: verify ownership.
    - Else: fallback to latest store (old behavior).
    """
    async with get_conn() as conn, conn.cursor() as cur:
        if store_id is not None:
            await cur.execute(
                "SELECT id FROM provider_stores WHERE id=%s AND owner_user_id=%s AND role=%s",
                (store_id, user_id, role),
            )
            r = await cur.fetchone()
            if not r:
                raise HTTPException(400, f"Invalid store_id for role={role}")
            return int(r[0])

    return await _my_store_id(user_id, role)


# --------------------------
# Store offers upsert (keep)
# --------------------------

class OfferUpsertIn(BaseModel):
    offer_id: Optional[int] = None  # update by offer_id
    sku_id: Optional[int] = None    # create/update by sku_id

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
async def upsert_offer(
    role: ProviderRole = Query(...),
    body: OfferUpsertIn = None,
    user_id: int = Depends(current_user_id),
    store_id: Optional[int] = Query(None),
):
    sid = await _require_store_id(user_id, role, store_id)

    if not body:
        raise HTTPException(400, "Body required")

    async with get_conn() as conn, conn.cursor() as cur:
        if body.offer_id:
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
                    body.offer_id, sid,
                ),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "Offer not found")
            return {"ok": True, "offer_id": int(row[0])}

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
                sid, body.sku_id,
                body.is_active, body.price, body.mrp, body.discount_pct,
                body.stock_qty, body.reorder_level,
                body.shipping_fee, body.eta_text, body.eta_days_min, body.eta_days_max,
                body.returnable, body.warranty_months,
            ),
        )
        oid = int((await cur.fetchone())[0])
        return {"ok": True, "offer_id": oid}


@router.get("/store/items", response_model=StoreOfferListOut)  # ✅ THIS TYPE, not StoreInventoryListOut
async def list_store_items(
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
    store_id: Optional[int] = Query(None),
):
    sid = await _require_store_id(user_id, role, store_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
              so.id AS offer_id,
              so.store_id,
              p.id AS product_id,
              s.id AS sku_id,
              p.category,
              p.title,
              COALESCE(b.name, p.brand_text) AS brand,
              CASE
                WHEN s.variant_key IS NOT NULL THEN (s.variant_key || ': ' || s.variant_value)
                ELSE NULL
              END AS variant,
              COALESCE(so.stock_qty, 0)::int AS stock_qty,
              COALESCE(so.reorder_level, 0)::int AS reorder_level,
              COALESCE(so.price, 0)::float AS price,
              so.mrp::float AS mrp,
              COALESCE(so.currency, 'INR') AS currency,
              so.is_active
            FROM store_offers so
            JOIN catalog_skus s ON so.sku_id = s.id
            JOIN catalog_products p ON s.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            WHERE so.store_id = %s
              AND so.is_active = TRUE
              AND s.is_active = TRUE
              AND p.is_active = TRUE
            ORDER BY p.title ASC, p.id DESC
            """,
            (sid,),   # ✅ ONLY ONE PARAM
        )
        rows = await cur.fetchall()

    keys = [
        "offer_id","store_id","product_id","sku_id",
        "category","title","brand","variant",
        "stock_qty","reorder_level","price","mrp","currency","is_active"
    ]
    return {"items": [dict(zip(keys, r)) for r in rows]}

# --------------------------
# Provider inventory (canonical)
# - returns ALL catalog_products with store_offers overlay
# - products without SKU => sku_id is NULL, offer fields default to 0/false
# --------------------------

@router.get("/store/inventory", response_model=StoreInventoryListOut)
async def list_inventory(
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
    store_id: Optional[int] = Query(None),
):
    sid = await _require_store_id(user_id, role, store_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            -- 1) REAL inventory: everything currently listed in this store (store_offers)
            WITH listed AS (
              SELECT
                so.id AS offer_id,
                so.store_id,
                p.id AS product_id,
                sku.id AS sku_id,
                p.category,
                p.title,
                COALESCE(b.name, p.brand_text) AS brand,
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
              LEFT JOIN brands b ON b.id = p.brand_id
              WHERE so.store_id = %s
            ),

            -- 2) UNLISTED catalog products: show as qty 0 (pick a representative sku if any)
            unlisted AS (
              SELECT
                NULL::int AS offer_id,
                %s::int AS store_id,
                p.id AS product_id,

                -- pick first active sku for display; may be NULL if product has no SKU
                (
                  SELECT s.id
                  FROM catalog_skus s
                  WHERE s.product_id = p.id AND s.is_active = TRUE
                  ORDER BY s.sort_order ASC, s.id ASC
                  LIMIT 1
                ) AS sku_id,

                p.category,
                p.title,
                COALESCE(b.name, p.brand_text) AS brand,

                -- variant for that rep sku (if exists)
                (
                  SELECT
                    CASE
                      WHEN s.variant_key IS NOT NULL AND s.variant_value IS NOT NULL
                        THEN (s.variant_key || ': ' || s.variant_value)
                      ELSE NULL
                    END
                  FROM catalog_skus s
                  WHERE s.product_id = p.id AND s.is_active = TRUE
                  ORDER BY s.sort_order ASC, s.id ASC
                  LIMIT 1
                ) AS variant,

                0::int AS stock_qty,
                0::int AS reorder_level,
                0::numeric AS price,
                NULL::numeric AS mrp,
                'INR'::text AS currency,
                FALSE AS is_active
              FROM catalog_products p
              LEFT JOIN brands b ON b.id = p.brand_id
              WHERE p.is_active = TRUE
                AND NOT EXISTS (
                  SELECT 1
                  FROM store_offers so
                  JOIN catalog_skus sku ON sku.id = so.sku_id
                  WHERE so.store_id = %s
                    AND sku.product_id = p.id
                )
            )

            SELECT * FROM listed
            UNION ALL
            SELECT * FROM unlisted
            ORDER BY title ASC, product_id DESC
            """,
            (sid, sid, sid),
        )
        rows = await cur.fetchall()

    keys = [
        "offer_id","store_id","product_id","sku_id",
        "category","title","brand","variant",
        "stock_qty","reorder_level","price","mrp","currency","is_active"
    ]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class AdjustStockIn(BaseModel):
    # preferred fast-path if UI has sku_id
    sku_id: Optional[int] = None

    # fallback if product has no sku yet
    product_id: Optional[int] = None

    delta: int
    reorder_level: Optional[int] = None


async def _ensure_sku_for_product(cur, product_id: int) -> int:
    """
    Lazy SKU creation:
    - If product already has an active SKU: use it
    - Else: create a default SKU (NULL variant) and return its id
    """
    await cur.execute(
        "SELECT id FROM catalog_skus WHERE product_id=%s AND is_active=TRUE ORDER BY sort_order ASC, id ASC LIMIT 1",
        (product_id,),
    )
    r = await cur.fetchone()
    if r:
        return int(r[0])

    await cur.execute(
        """
        INSERT INTO catalog_skus
          (product_id, variant_key, variant_value, pack_label, sku_code, barcode, sort_order, is_active)
        VALUES
          (%s, NULL, NULL, NULL, NULL, NULL, 0, TRUE)
        RETURNING id
        """,
        (product_id,),
    )
    return int((await cur.fetchone())[0])


@router.post("/store/inventory/adjust", response_model=AdjustStockOut)
async def adjust_stock(
    role: ProviderRole = Query(...),
    body: AdjustStockIn = None,
    user_id: int = Depends(current_user_id),
    store_id: Optional[int] = Query(None),
):
    if not body:
        raise HTTPException(400, "Body required")

    sid = await _require_store_id(user_id, role, store_id)

    async with get_conn() as conn, conn.cursor() as cur:
        sku_id = body.sku_id

        if sku_id is None:
            if body.product_id is None:
                raise HTTPException(400, "Provide sku_id or product_id")

            await cur.execute("SELECT id FROM catalog_products WHERE id=%s", (body.product_id,))
            if not await cur.fetchone():
                raise HTTPException(404, "Product not found")

            sku_id = await _ensure_sku_for_product(cur, int(body.product_id))

        # Ensure offer exists (create if missing)
        await cur.execute(
            "SELECT id FROM store_offers WHERE store_id=%s AND sku_id=%s",
            (sid, sku_id),
        )
        row = await cur.fetchone()

        if not row:
            await cur.execute(
                """
                INSERT INTO store_offers (store_id, sku_id, is_active, currency, price, stock_qty, reorder_level)
                VALUES (%s, %s, TRUE, 'INR', 0, 0, COALESCE(%s,0))
                ON CONFLICT (store_id, sku_id) DO NOTHING
                RETURNING id
                """,
                (sid, sku_id, body.reorder_level),
            )
            created = await cur.fetchone()
            if created:
                offer_id = int(created[0])
            else:
                await cur.execute("SELECT id FROM store_offers WHERE store_id=%s AND sku_id=%s", (sid, sku_id))
                offer_id = int((await cur.fetchone())[0])
        else:
            offer_id = int(row[0])

        await cur.execute(
            """
            UPDATE store_offers SET
              stock_qty = GREATEST(stock_qty + %s, 0),
              reorder_level = COALESCE(%s, reorder_level),
              updated_at=now()
            WHERE id=%s AND store_id=%s
            RETURNING id, stock_qty, sku_id
            """,
            (body.delta, body.reorder_level, offer_id, sid),
        )
        r2 = await cur.fetchone()
        if not r2:
            raise HTTPException(404, "Offer not found after upsert")

        oid, qty, sku_id2 = r2

    return {"ok": True, "offer_id": int(oid), "sku_id": int(sku_id2), "stock_qty": int(qty)}
