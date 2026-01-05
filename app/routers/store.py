from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal, List
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

CatalogKind = Literal["PRODUCT", "SERVICE"]  # or whatever your UI enum is
CatalogCategory = Literal["FOOD","ACCESSORY","MEDICINE","SERVICE"]

class CatalogUpsertIn(BaseModel):
    id: Optional[int] = None

    # UI field names
    provider_id: Optional[int] = None
    kind: Optional[CatalogKind] = None

    name: str
    description: Optional[str] = None
    category: CatalogCategory

    price: float = 0
    active: bool = True

    rx_required: bool = False
    image_uri: Optional[str] = None

    # If you want to keep DB fields but accept UI names too:
    # (Not required, but handy)
    currency: str = "INR"
    brand: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "ignore"   # ignore any future UI fields

@router.get("/store/items")
async def list_my_items(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id,
                      store_id as provider_id,
                      'PRODUCT' as kind,
                      category,
                      title as name,
                      description,
                      price,
                      is_active as active,
                      prescription_required as rx_required,
                      image_uri
               FROM store_items
               WHERE store_id=%s
               ORDER BY id DESC""",
            (store_id,),
        )
        rows = await cur.fetchall()

    keys = ["id","provider_id","kind","category","name","description","price","active","rx_required","image_uri"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.post("/store/items")
async def upsert_item(role: ProviderRole = Query(...), body: CatalogUpsertIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)

    async with get_conn() as conn, conn.cursor() as cur:
        if body.id:
            await cur.execute(
                """UPDATE store_items SET
                      title=%s,
                      description=%s,
                      category=%s,
                      image_uri=%s,
                      price=%s,
                      currency=%s,
                      is_active=%s,
                      prescription_required=%s,
                      updated_at=now()
                   WHERE id=%s AND store_id=%s
                   RETURNING id""",
                (
                    body.name,
                    body.description,
                    body.category,
                    body.image_uri,
                    body.price,
                    body.currency,
                    body.active,
                    body.rx_required,
                    body.id,
                    store_id,
                ),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "Item not found")
            item_id = row[0]
        else:
            await cur.execute(
                """INSERT INTO store_items
                   (store_id, title, description, category, image_uri, price, currency, is_active, prescription_required)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    store_id,
                    body.name,
                    body.description,
                    body.category,
                    body.image_uri,
                    body.price,
                    body.currency,
                    body.active,
                    body.rx_required,
                ),
            )
            item_id = (await cur.fetchone())[0]

    return {"ok": True, "id": item_id}

@router.get("/shop/items/{item_id}")
async def get_shop_item(
    item_id: int,
    user_id: int = Depends(current_user_id),
):
    sql = """
      SELECT
        it.id,
        it.store_id as provider_id,
        'PRODUCT' as kind,
        it.category,
        it.title as name,
        it.description,
        it.brand,
        it.image_uri,
        it.price,
        it.currency,
        it.is_active as active,
        it.prescription_required as rx_required,
        s.display_name as store_name,
        COALESCE(inv.stock_qty, 0) as stock_qty
      FROM store_items it
      JOIN provider_stores s ON s.id = it.store_id
      LEFT JOIN store_inventory inv
        ON inv.catalog_item_id = it.id AND inv.store_id = it.store_id
      WHERE it.id = %s
        AND it.is_active = TRUE
    """

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(sql, (item_id,))
        row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Item not found")

    keys = [
        "id",
        "provider_id",
        "kind",
        "category",
        "name",
        "description",
        "brand",
        "image_uri",
        "price",
        "currency",
        "active",
        "rx_required",
        "store_name",
        "stock_qty",
    ]
    return {"item": dict(zip(keys, row))}

@router.get("/store/inventory")
async def list_inventory(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT i.id, i.store_id, i.catalog_item_id, i.stock_qty, i.reorder_level, i.batch_no, i.expiry_date,
                      it.title, it.category
               FROM store_inventory i
               JOIN store_items it ON it.id=i.catalog_item_id
               WHERE i.store_id=%s
               ORDER BY it.title""",
            (store_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","store_id","catalog_item_id","stock_qty","reorder_level","batch_no","expiry_date","title","category"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class AdjustStockIn(BaseModel):
    catalog_item_id: int
    delta: int
    reorder_level: Optional[int] = None
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None  # YYYY-MM-DD

@router.post("/store/inventory/adjust")
async def adjust_stock(role: ProviderRole = Query(...), body: AdjustStockIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO store_inventory (store_id, catalog_item_id, stock_qty, reorder_level, batch_no, expiry_date)
               VALUES (%s,%s,%s,COALESCE(%s,0),%s,%s::date)
               ON CONFLICT (store_id, catalog_item_id) DO UPDATE SET
                 stock_qty = store_inventory.stock_qty + EXCLUDED.stock_qty,
                 reorder_level = COALESCE(EXCLUDED.reorder_level, store_inventory.reorder_level),
                 batch_no = COALESCE(EXCLUDED.batch_no, store_inventory.batch_no),
                 expiry_date = COALESCE(EXCLUDED.expiry_date, store_inventory.expiry_date),
                 updated_at=now()
               RETURNING id, stock_qty""",
            (store_id, body.catalog_item_id, body.delta, body.reorder_level, body.batch_no, body.expiry_date),
        )
        inv_id, qty = await cur.fetchone()
    return {"ok": True, "inventory_id": inv_id, "stock_qty": qty}

# Provider order ops
@router.get("/provider/orders")
async def list_provider_orders(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, buyer_user_id, store_id, status, total_amount, currency, created_at,
                      prescription_required, prescription_attached
               FROM orders WHERE store_id=%s ORDER BY id DESC""",
            (store_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","buyer_user_id","store_id","status","total_amount","currency","created_at","prescription_required","prescription_attached"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

class StatusIn(BaseModel):
    status: str

@router.patch("/provider/orders/{order_id}/status")
async def set_order_status(order_id: int, role: ProviderRole = Query(...), body: StatusIn = None, user_id: int = Depends(current_user_id)):
    store_id = await _my_store_id(user_id, role)
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """UPDATE orders SET status=%s, updated_at=now()
               WHERE id=%s AND store_id=%s
               RETURNING id""",
            (body.status, order_id, store_id),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Order not found")
    return {"ok": True}
