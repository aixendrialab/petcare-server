from fastapi import APIRouter, Depends, Query
from app.routers.security import current_user_id
from app.core.db import get_conn
from typing import Optional, Literal

router = APIRouter()

Category = Literal["FOOD","ACCESSORY","MEDICINE","SERVICE"]

@router.get("/shop/stores")
async def list_stores(role: str = Query("vendor"), city: Optional[str] = None, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        if city:
            await cur.execute(
                """SELECT id, role, display_name, city, state, pincode, status
                   FROM provider_stores
                   WHERE role=%s AND status='ACTIVE' AND city=%s
                   ORDER BY id DESC""",
                (role, city),
            )
        else:
            await cur.execute(
                """SELECT id, role, display_name, city, state, pincode, status
                   FROM provider_stores
                   WHERE role=%s AND status='ACTIVE'
                   ORDER BY id DESC""",
                (role,),
            )
        rows = await cur.fetchall()
    keys = ["id","role","display_name","city","state","pincode","status"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.get("/shop/items")
async def list_items(
    category: Optional[Category] = None,
    store_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 50,
    user_id: int = Depends(current_user_id),
):
    where = ["it.is_active=TRUE", "s.status='ACTIVE'"]  # also hide inactive stores
    params = []

    if category:
        where.append("it.category=%s")
        params.append(category)

    if store_id:
        where.append("it.store_id=%s")
        params.append(store_id)

    # ✅ normalize q without “functions”
    if q is not None:
        q = q.strip()
        q = _none_if_undefined(q)
        if q == "" or q.lower() in ("undefined", "null"):
            q = None

    if q:
        where.append("(it.title ILIKE %s OR it.description ILIKE %s OR it.brand ILIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = f"""
      SELECT it.id, it.store_id, it.title, it.description, it.category, it.brand, it.image_uri,
             it.price, it.currency, it.prescription_required,
             s.display_name as store_name,
             COALESCE(inv.stock_qty, 0) as stock_qty
      FROM store_items it
      JOIN provider_stores s ON s.id=it.store_id
      LEFT JOIN store_inventory inv ON inv.catalog_item_id=it.id AND inv.store_id=it.store_id
      WHERE {" AND ".join(where)}
      ORDER BY it.id DESC
      LIMIT {int(limit)}
    """

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(sql, tuple(params))
        rows = await cur.fetchall()

    keys = ["id","store_id","title","description","category","brand","image_uri",
            "price","currency","prescription_required","store_name","stock_qty"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

def _none_if_undefined(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if v in ("undefined", "null", ""):
        return None
    return v