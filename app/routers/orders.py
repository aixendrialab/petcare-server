from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class CheckoutItemIn(BaseModel):
    catalog_item_id: int
    qty: int

class CheckoutIn(BaseModel):
    store_id: int
    items: List[CheckoutItemIn]
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None

class OrderItemIn(BaseModel):
    catalog_item_id: int
    qty: int

class PlaceOrderIn(BaseModel):
    provider_id: int
    items: List[CheckoutItemIn]
    prescription_id: Optional[int] = None
    rx_uri: Optional[str] = None

    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    
@router.post("/orders/checkout")
async def checkout(body: CheckoutIn, user_id: int = Depends(current_user_id)):
    if not body.items:
        raise HTTPException(400, "No items")

    async with get_conn() as conn, conn.cursor() as cur:
        # Load item prices + title
        ids = [it.catalog_item_id for it in body.items]
        await cur.execute(
            f"""SELECT id, title, price, currency, prescription_required
                FROM store_items
                WHERE store_id=%s AND id = ANY(%s) AND is_active=TRUE""",
            (body.store_id, ids),
        )
        rows = await cur.fetchall()
        by_id = {r[0]: r for r in rows}
        if len(by_id) != len(ids):
            raise HTTPException(400, "Some items are invalid/inactive")

        total = 0.0
        currency = rows[0][3] if rows else "INR"
        rx_required = any(bool(by_id[i][4]) for i in ids)

        await cur.execute(
            """INSERT INTO orders
               (buyer_user_id, store_id, status, total_amount, currency,
                address_line1, address_line2, city, state, pincode,
                prescription_required, prescription_attached)
               VALUES (%s,%s,'CREATED',%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
               RETURNING id""",
            (user_id, body.store_id, total, currency,
             body.address_line1, body.address_line2, body.city, body.state, body.pincode,
             rx_required),
        )
        order_id = (await cur.fetchone())[0]

        # Insert items + compute totals
        for it in body.items:
            _, title, price, _, _ = by_id[it.catalog_item_id]
            line_total = float(price) * int(it.qty)
            total += line_total
            await cur.execute(
                """INSERT INTO order_items (order_id, catalog_item_id, title_snapshot, unit_price, qty, line_total)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (order_id, it.catalog_item_id, title, price, it.qty, line_total),
            )

        await cur.execute("UPDATE orders SET total_amount=%s, updated_at=now() WHERE id=%s", (total, order_id))

    return {"ok": True, "order_id": order_id}

@router.get("/orders")
async def my_orders(mine: int = 1, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, store_id, status, total_amount, currency, created_at
               FROM orders WHERE buyer_user_id=%s ORDER BY id DESC""",
            (user_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","store_id","status","total_amount","currency","created_at"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.get("/orders/{order_id}")
async def order_detail(order_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, buyer_user_id, store_id, status, total_amount, currency, created_at,
                      address_line1, address_line2, city, state, pincode
               FROM orders WHERE id=%s AND buyer_user_id=%s""",
            (order_id, user_id),
        )
        o = await cur.fetchone()
        if not o:
            raise HTTPException(404, "Order not found")

        await cur.execute(
            """SELECT catalog_item_id, title_snapshot, unit_price, qty, line_total
               FROM order_items WHERE order_id=%s ORDER BY id""",
            (order_id,),
        )
        items = await cur.fetchall()

    okeys = ["id","buyer_user_id","store_id","status","total_amount","currency","created_at",
             "address_line1","address_line2","city","state","pincode"]
    ikeys = ["catalog_item_id","title","unit_price","qty","line_total"]
    return {"order": dict(zip(okeys, o)), "items": [dict(zip(ikeys, r)) for r in items]}


@router.post("/orders")
async def place_order(body: PlaceOrderIn, user_id: int = Depends(current_user_id)):
    if not body.items:
        raise HTTPException(400, "No items")

    store_id = body.provider_id  # your UI uses provider_id; DB uses store_id

    async with get_conn() as conn, conn.cursor() as cur:
        # 1) Load catalog items (price, title, currency, rx flag)
        ids = [it.catalog_item_id for it in body.items]

        await cur.execute(
            """
            SELECT id, title, price, currency, prescription_required
            FROM store_items
            WHERE store_id=%s AND id = ANY(%s) AND is_active=TRUE
            """,
            (store_id, ids),
        )
        rows = await cur.fetchall()
        by_id = {r[0]: r for r in rows}

        if len(by_id) != len(ids):
            raise HTTPException(400, "Some items are invalid/inactive")

        currency = rows[0][3] if rows else "INR"
        rx_required = any(bool(by_id[i][4]) for i in ids)

        # 2) Create order with placeholder total 0 first
        await cur.execute(
            """
            INSERT INTO orders
              (buyer_user_id, store_id, status, total_amount, currency,
               prescription_required, prescription_attached)
            VALUES
              (%s, %s, 'CREATED', %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, store_id, 0.0, currency, rx_required, False),
        )
        order_id = (await cur.fetchone())[0]

        # 3) Insert order items and compute total
        total = 0.0
        for it in body.items:
            _, title, price, _, _rx = by_id[it.catalog_item_id]
            qty = int(it.qty)
            unit_price = float(price)
            line_total = unit_price * qty
            total += line_total

            await cur.execute(
                """
                INSERT INTO order_items
                  (order_id, catalog_item_id, title_snapshot, unit_price, qty, line_total)
                VALUES
                  (%s, %s, %s, %s, %s, %s)
                """,
                (order_id, it.catalog_item_id, title, unit_price, qty, line_total),
            )

        # 4) Update order total
        await cur.execute(
            "UPDATE orders SET total_amount=%s, updated_at=now() WHERE id=%s",
            (total, order_id),
        )

        # Optional: clear cart after placing (if you have cart tables)
        # await cur.execute("DELETE FROM cart_items WHERE buyer_user_id=%s AND store_id=%s", (user_id, store_id))

    return {"order_id": order_id}