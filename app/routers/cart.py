from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class CartAddIn(BaseModel):
    offer_id: int
    qty: int = 1

class CartQtyIn(BaseModel):
    qty: int

class CartAddressIn(BaseModel):
    address_id: int

async def _ensure_cart(user_id: int) -> int:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO carts (parent_user_id)
               VALUES (%s)
               ON CONFLICT (parent_user_id) DO NOTHING""",
            (user_id,),
        )
        await cur.execute("SELECT id FROM carts WHERE parent_user_id=%s", (user_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(500, "Failed to create/find cart")
        return int(row[0])

@router.post("/cart/address")
async def set_cart_address(body: CartAddressIn, user_id: int = Depends(current_user_id)):
    cart_id = await _ensure_cart(user_id)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM user_addresses WHERE id=%s AND user_id=%s", (body.address_id, user_id))
        if not await cur.fetchone():
            raise HTTPException(400, "Invalid address")

        await cur.execute("UPDATE carts SET address_id=%s, updated_at=now() WHERE id=%s", (body.address_id, cart_id))
    return {"ok": True}

@router.post("/cart/items")
async def add_to_cart(body: CartAddIn, user_id: int = Depends(current_user_id)):
    if body.qty <= 0:
        raise HTTPException(400, "qty must be > 0")

    cart_id = await _ensure_cart(user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        # offer exists + active
        await cur.execute("SELECT id, is_active FROM store_offers WHERE id=%s", (body.offer_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(404, "Offer not found")
        if r[1] is not True:
            raise HTTPException(400, "Offer is not active")

        await cur.execute(
            """INSERT INTO cart_items (cart_id, store_offer_id, qty)
               VALUES (%s,%s,%s)
               ON CONFLICT (cart_id, store_offer_id) DO UPDATE SET
                 qty = cart_items.qty + EXCLUDED.qty,
                 updated_at = now()
               RETURNING id, qty""",
            (cart_id, body.offer_id, body.qty),
        )
        cart_item_id, qty = await cur.fetchone()

        await cur.execute("UPDATE carts SET updated_at=now() WHERE id=%s", (cart_id,))

    return {"ok": True, "cart_item_id": cart_item_id, "qty": qty}

@router.patch("/cart/items/{cart_item_id}")
async def set_cart_item_qty(cart_item_id: int, body: CartQtyIn, user_id: int = Depends(current_user_id)):
    if body.qty <= 0:
        raise HTTPException(400, "qty must be > 0")

    cart_id = await _ensure_cart(user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """UPDATE cart_items SET qty=%s, updated_at=now()
               WHERE id=%s AND cart_id=%s
               RETURNING id""",
            (body.qty, cart_item_id, cart_id),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Cart item not found")
    return {"ok": True}

@router.delete("/cart/items/{cart_item_id}")
async def delete_cart_item(cart_item_id: int, user_id: int = Depends(current_user_id)):
    cart_id = await _ensure_cart(user_id)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM cart_items WHERE id=%s AND cart_id=%s RETURNING id", (cart_item_id, cart_id))
        if not await cur.fetchone():
            raise HTTPException(404, "Cart item not found")
    return {"ok": True}

@router.get("/cart")
async def get_cart(mine: int = Query(0), user_id: int = Depends(current_user_id)):
    if int(mine) != 1:
        raise HTTPException(400, "Use mine=1")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, address_id FROM carts WHERE parent_user_id=%s", (user_id,))
        row = await cur.fetchone()
        if not row:
            return {"items": [], "totals": {"items_total": 0, "discount_total": 0, "shipping_fee": 0, "tax_total": 0, "grand_total": 0}, "address": None}

        cart_id, address_id = int(row[0]), row[1]

        addr = None
        if address_id:
            await cur.execute(
                """SELECT id,label,recipient,phone,line1,line2,landmark,city,state,pincode,lat,lng,is_default
                   FROM user_addresses WHERE id=%s AND user_id=%s""",
                (address_id, user_id),
            )
            a = await cur.fetchone()
            if a:
                keys = ["id","label","recipient","phone","line1","line2","landmark","city","state","pincode","lat","lng","is_default"]
                addr = dict(zip(keys, a))

        await cur.execute(
            """
            SELECT
              ci.id as cart_item_id,
              ci.qty,
              so.id as offer_id,
              so.price, so.mrp, so.currency, so.discount_pct,
              so.stock_qty,
              ps.id as store_id, ps.display_name,
              p.id as product_id, p.title,
              sku.id as sku_id, sku.variant_key, sku.variant_value, sku.pack_label,
              pm.uri as primary_image,
              tc.gst_pct
            FROM cart_items ci
            JOIN store_offers so ON so.id = ci.store_offer_id
            JOIN provider_stores ps ON ps.id = so.store_id
            JOIN catalog_skus sku ON sku.id = so.sku_id
            JOIN catalog_products p ON p.id = sku.product_id
            LEFT JOIN LATERAL (
              SELECT uri FROM product_media
              WHERE product_id = p.id AND media_type='IMAGE'
              ORDER BY sort_order ASC, id ASC
              LIMIT 1
            ) pm ON TRUE
            LEFT JOIN tax_classes tc ON tc.code = p.tax_class
            WHERE ci.cart_id=%s
            ORDER BY ci.id DESC
            """,
            (cart_id,),
        )
        rows = await cur.fetchall()

    items = []
    items_total = 0.0
    discount_total = 0.0
    shipping_fee = 0.0
    tax_total = 0.0

    for r in rows:
        (
            cart_item_id, qty,
            offer_id,
            price, mrp, currency, discount_pct,
            stock_qty,
            store_id, store_name,
            product_id, product_title,
            sku_id, vkey, vval, pack_label,
            primary_image,
            gst_pct
        ) = r

        qty = int(qty)
        unit_price = float(price)
        line = unit_price * qty

        # simple discount calc from mrp if present
        if mrp and float(mrp) > unit_price:
            discount_total += (float(mrp) - unit_price) * qty

        items_total += line

        g = float(gst_pct or 0.0)
        tax_total += (line * g / 100.0)

        items.append({
            "cart_item_id": cart_item_id,
            "offer_id": offer_id,
            "store": {"id": store_id, "display_name": store_name},
            "product_id": product_id,
            "sku_id": sku_id,
            "title": product_title,
            "variant": f"{vkey}:{vval}" if vkey and vval else (pack_label or None),
            "qty": qty,
            "unit_price": unit_price,
            "currency": currency,
            "line_total": line,
            "primary_image": primary_image,
            "in_stock": (int(stock_qty or 0) > 0),
        })

    grand_total = items_total + shipping_fee + tax_total

    return {
        "items": items,
        "address": addr,
        "totals": {
            "items_total": items_total,
            "discount_total": discount_total,
            "shipping_fee": shipping_fee,
            "tax_total": tax_total,
            "grand_total": grand_total,
        },
    }
