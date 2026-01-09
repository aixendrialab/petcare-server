from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Literal
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

OrderStatus = Literal["CREATED","CONFIRMED","PACKED","DISPATCHED","DELIVERED","CANCELLED"]

class CheckoutIn(BaseModel):
    address_id: int  # required

@router.post("/orders/checkout")
async def checkout(body: CheckoutIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        # cart exists
        await cur.execute("SELECT id FROM carts WHERE parent_user_id=%s", (user_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(400, "Cart not found")
        cart_id = int(r[0])

        # validate address
        await cur.execute("SELECT id FROM user_addresses WHERE id=%s AND user_id=%s", (body.address_id, user_id))
        if not await cur.fetchone():
            raise HTTPException(400, "Invalid address")

        # load cart items with offer/product/tax
        await cur.execute(
            """
            SELECT
              ci.id as cart_item_id,
              ci.qty,
              so.id as offer_id,
              so.store_id,
              so.currency, so.price, so.mrp, so.discount_pct,
              so.shipping_fee,
              so.stock_qty,
              sku.id as sku_id,
              p.id as product_id,
              p.title,
              p.tax_class,
              tc.gst_pct
            FROM cart_items ci
            JOIN store_offers so ON so.id=ci.store_offer_id AND so.is_active=TRUE
            JOIN catalog_skus sku ON sku.id=so.sku_id
            JOIN catalog_products p ON p.id=sku.product_id
            LEFT JOIN tax_classes tc ON tc.code=p.tax_class
            WHERE ci.cart_id=%s
            ORDER BY so.store_id, ci.id
            """,
            (cart_id,),
        )
        rows = await cur.fetchall()
        if not rows:
            raise HTTPException(400, "Cart is empty")

        # group by store_id -> one order per store
        by_store: dict[int, list] = {}
        for row in rows:
            store_id = int(row[3])
            by_store.setdefault(store_id, []).append(row)

        created_orders: List[int] = []

        for store_id, items in by_store.items():
            currency = items[0][4] or "INR"

            items_total = 0.0
            discount_total = 0.0
            shipping_fee = 0.0
            tax_total = 0.0

            # create order placeholder
            await cur.execute(
                """
                INSERT INTO orders
                  (parent_user_id, store_id, address_id, status, currency,
                   items_total, discount_total, shipping_fee, tax_total, grand_total)
                VALUES
                  (%s,%s,%s,'CREATED',%s,0,0,0,0,0)
                RETURNING id
                """,
                (user_id, store_id, body.address_id, currency),
            )
            order_id = int((await cur.fetchone())[0])
            created_orders.append(order_id)

            for row in items:
                cart_item_id, qty, offer_id, _store_id, currency, price, mrp, dpct, ship_fee, stock_qty, sku_id, product_id, title, tax_class, gst_pct = row
                qty = int(qty)

                if int(stock_qty or 0) < qty:
                    raise HTTPException(400, f"Out of stock for offer_id={offer_id}")

                unit_price = float(price)
                line = unit_price * qty
                items_total += line

                # discount from mrp if present
                disc_amt = 0.0
                if mrp is not None and float(mrp) > unit_price:
                    disc_amt = (float(mrp) - unit_price) * qty
                    discount_total += disc_amt

                # tax
                g = float(gst_pct or 0.0)
                gst_amt = line * g / 100.0
                tax_total += gst_amt

                # shipping fee at order-level: max of offer shipping_fee
                if ship_fee is not None:
                    shipping_fee = max(shipping_fee, float(ship_fee))

                variant_snapshot = None  # can be filled via sku fields later
                await cur.execute(
                    """
                    INSERT INTO order_items
                      (order_id, store_offer_id, sku_id, product_id,
                       title_snapshot, variant_snapshot, qty,
                       unit_price, mrp, discount_amt, gst_pct, gst_amt, line_total)
                    VALUES
                      (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        order_id, offer_id, sku_id, product_id,
                        title, variant_snapshot, qty,
                        unit_price, float(mrp) if mrp is not None else None, disc_amt,
                        g, gst_amt, line
                    ),
                )

                # decrement stock
                await cur.execute(
                    "UPDATE store_offers SET stock_qty = GREATEST(stock_qty - %s, 0), updated_at=now() WHERE id=%s",
                    (qty, offer_id),
                )

            grand_total = items_total - discount_total + shipping_fee + tax_total

            await cur.execute(
                """
                UPDATE orders SET
                  items_total=%s,
                  discount_total=%s,
                  shipping_fee=%s,
                  tax_total=%s,
                  grand_total=%s
                WHERE id=%s
                """,
                (items_total, discount_total, shipping_fee, tax_total, grand_total, order_id),
            )

        # clear cart
        await cur.execute("DELETE FROM cart_items WHERE cart_id=%s", (cart_id,))

    return {"ok": True, "order_ids": created_orders}

@router.get("/orders")
async def my_orders(mine: int = Query(1), user_id: int = Depends(current_user_id)):
    if int(mine) != 1:
        raise HTTPException(400, "Use mine=1")
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT o.id, o.store_id, ps.display_name, o.status,
                   o.grand_total, o.currency, o.created_at
            FROM orders o
            JOIN provider_stores ps ON ps.id=o.store_id
            WHERE o.parent_user_id=%s
            ORDER BY o.id DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","store_id","store_name","status","grand_total","currency","created_at"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.get("/orders/{order_id}")
async def order_detail(order_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT o.id, o.parent_user_id, o.store_id, ps.display_name, o.status, o.created_at,
                   o.currency, o.items_total, o.discount_total, o.shipping_fee, o.tax_total, o.grand_total,
                   a.label, a.recipient, a.phone, a.line1, a.line2, a.landmark, a.city, a.state, a.pincode
            FROM orders o
            JOIN provider_stores ps ON ps.id=o.store_id
            JOIN user_addresses a ON a.id=o.address_id
            WHERE o.id=%s AND o.parent_user_id=%s
            """,
            (order_id, user_id),
        )
        o = await cur.fetchone()
        if not o:
            raise HTTPException(404, "Order not found")

        await cur.execute(
            """
            SELECT oi.product_id, oi.sku_id, oi.qty, oi.unit_price, oi.mrp, oi.discount_amt, oi.gst_pct, oi.gst_amt, oi.line_total,
                   oi.title_snapshot
            FROM order_items oi
            WHERE oi.order_id=%s
            ORDER BY oi.id
            """,
            (order_id,),
        )
        items = await cur.fetchall()

    order = {
        "id": o[0],
        "store": {"id": o[2], "display_name": o[3]},
        "status": o[4],
        "created_at": o[5].isoformat() if hasattr(o[5], "isoformat") else str(o[5]),
        "currency": o[6],
        "totals": {
            "items_total": float(o[7]),
            "discount_total": float(o[8]),
            "shipping_fee": float(o[9]),
            "tax_total": float(o[10]),
            "grand_total": float(o[11]),
        },
        "address": {
            "label": o[12], "recipient": o[13], "phone": o[14],
            "line1": o[15], "line2": o[16], "landmark": o[17],
            "city": o[18], "state": o[19], "pincode": o[20],
        },
        "items": [],
    }

    for r in items:
        (product_id, sku_id, qty, unit_price, mrp, disc, gst_pct, gst_amt, line_total, title) = r
        order["items"].append({
            "product_id": int(product_id),
            "sku_id": int(sku_id),
            "title": title,
            "qty": int(qty),
            "unit_price": float(unit_price),
            "mrp": float(mrp) if mrp is not None else None,
            "discount_amt": float(disc),
            "gst_pct": float(gst_pct),
            "gst_amt": float(gst_amt),
            "line_total": float(line_total),
        })

    return {"order": order}

# --------------------------
# Provider ops
# --------------------------

ProviderRole = Literal["vendor","pharmacist","nutritionist","hostel"]

async def _my_store_id(user_id: int, role: str) -> int:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM provider_stores WHERE owner_user_id=%s AND role=%s",
            (user_id, role),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(400, f"No store profile for role={role}. Complete onboarding first.")
        return int(row[0])

@router.get("/provider/orders")
async def provider_orders(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT o.id, o.parent_user_id, o.status, o.grand_total, o.currency, o.created_at
            FROM orders o
            WHERE o.store_id=%s
            ORDER BY o.id DESC
            """,
            (store_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","parent_user_id","status","grand_total","currency","created_at"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class StatusIn(BaseModel):
    status: OrderStatus

@router.patch("/provider/orders/{order_id}/status")
async def set_provider_order_status(order_id: int, role: ProviderRole = Query(...), body: StatusIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE orders SET status=%s WHERE id=%s AND store_id=%s RETURNING id",
            (body.status, order_id, store_id),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Order not found")
    return {"ok": True}
