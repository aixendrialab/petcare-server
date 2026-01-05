from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class AddToCartIn(BaseModel):
    catalog_item_id: int
    qty: int = 1

async def _ensure_cart_id(user_id: int) -> int:
    async with get_conn() as conn, conn.cursor() as cur:
        # Create cart if not exists
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

@router.post("/cart/items")
async def add_to_cart(body: AddToCartIn, user_id: int = Depends(current_user_id)):
    if body.qty <= 0:
        raise HTTPException(400, "qty must be > 0")

    async with get_conn() as conn, conn.cursor() as cur:
        # Validate item exists + active
        await cur.execute(
            "SELECT id, is_active FROM store_items WHERE id=%s",
            (body.catalog_item_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Catalog item not found")
        if row[1] is not True:
            raise HTTPException(400, "Item is not active")

        cart_id = await _ensure_cart_id(user_id)

        # Upsert line item: add qty if already exists
        await cur.execute(
            """INSERT INTO cart_items (cart_id, catalog_item_id, qty)
               VALUES (%s, %s, %s)
               ON CONFLICT (cart_id, catalog_item_id) DO UPDATE SET
                 qty = cart_items.qty + EXCLUDED.qty,
                 updated_at = now()
               RETURNING id, qty""",
            (cart_id, body.catalog_item_id, body.qty),
        )
        item_id, qty = await cur.fetchone()

        await cur.execute("UPDATE carts SET updated_at=now() WHERE id=%s", (cart_id,))

    return {"ok": True, "cart_item_id": item_id, "qty": qty}

@router.get("/cart")
async def get_cart(mine: int = Query(0), user_id: int = Depends(current_user_id)):
    # your UI calls /cart?mine=1
    if int(mine) != 1:
        raise HTTPException(400, "Use mine=1")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM carts WHERE parent_user_id=%s", (user_id,))
        row = await cur.fetchone()
        if not row:
            return {"items": [], "total_amount": 0}

        cart_id = int(row[0])

        await cur.execute(
            """SELECT ci.id,
                      ci.catalog_item_id,
                      ci.qty,
                      it.title,
                      it.price,
                      it.currency,
                      it.store_id,
                      s.display_name as store_name
               FROM cart_items ci
               JOIN store_items it ON it.id = ci.catalog_item_id
               JOIN provider_stores s ON s.id = it.store_id
               WHERE ci.cart_id=%s
               ORDER BY ci.id DESC""",
            (cart_id,),
        )
        rows = await cur.fetchall()

    items = []
    total = 0.0
    for r in rows:
        # id, catalog_item_id, qty, title, price, currency, store_id, store_name
        line_total = float(r[4]) * int(r[2])
        total += line_total
        items.append({
            "id": r[0],
            "catalog_item_id": r[1],
            "qty": r[2],
            "name": r[3],
            "price": float(r[4]),
            "currency": r[5],
            "provider_id": r[6],
            "store_name": r[7],
            "line_total": line_total,
        })

    return {"items": items, "total_amount": total}
