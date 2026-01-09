from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class WishIn(BaseModel):
    product_id: int

@router.get("/wishlist")
async def wishlist(mine: int = Query(1), user_id: int = Depends(current_user_id)):
    if int(mine) != 1:
        raise HTTPException(400, "Use mine=1")
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM wishlists WHERE user_id=%s", (user_id,))
        w = await cur.fetchone()
        if not w:
            return {"items": []}
        wid = int(w[0])

        await cur.execute(
            """
            SELECT p.id, p.category, p.title,
                   pm.uri
            FROM wishlist_items wi
            JOIN catalog_products p ON p.id=wi.product_id
            LEFT JOIN LATERAL (
              SELECT uri FROM product_media
              WHERE product_id=p.id AND media_type='IMAGE'
              ORDER BY sort_order ASC, id ASC LIMIT 1
            ) pm ON TRUE
            WHERE wi.wishlist_id=%s
            ORDER BY wi.id DESC
            """,
            (wid,),
        )
        rows = await cur.fetchall()

    return {"items": [{"product_id": r[0], "category": r[1], "title": r[2], "primary_image": r[3]} for r in rows]}

@router.post("/wishlist/items")
async def add_wishlist_item(body: WishIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("INSERT INTO wishlists (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        await cur.execute("SELECT id FROM wishlists WHERE user_id=%s", (user_id,))
        wid = int((await cur.fetchone())[0])

        await cur.execute("SELECT id FROM catalog_products WHERE id=%s", (body.product_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")

        await cur.execute(
            "INSERT INTO wishlist_items (wishlist_id, product_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (wid, body.product_id),
        )
    return {"ok": True}

@router.delete("/wishlist/items/{product_id}")
async def remove_wishlist_item(product_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM wishlists WHERE user_id=%s", (user_id,))
        w = await cur.fetchone()
        if not w:
            return {"ok": True}
        wid = int(w[0])
        await cur.execute("DELETE FROM wishlist_items WHERE wishlist_id=%s AND product_id=%s", (wid, product_id))
    return {"ok": True}
