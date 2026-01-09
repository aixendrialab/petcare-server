from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Literal
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class ReviewIn(BaseModel):
    sku_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    body: str
    is_verified_purchase: bool = False

class VoteIn(BaseModel):
    is_helpful: bool

# --------------------------
# Product reviews
# --------------------------

@router.get("/shop/products/{product_id}/reviews")
async def product_reviews(
    product_id: int,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    sort: Literal["recent","helpful"] = Query("recent"),
    user_id: int = Depends(current_user_id),
):
    order_sql = "ORDER BY r.created_at DESC" if sort == "recent" else """
      ORDER BY (
        SELECT COUNT(*) FROM review_votes v WHERE v.review_id=r.id AND v.is_helpful=TRUE
      ) DESC, r.created_at DESC
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT r.id, u.name, r.rating, r.title, r.body, r.created_at, r.is_verified_purchase
            FROM item_reviews r
            JOIN users u ON u.id=r.user_id
            WHERE r.product_id=%s
            {order_sql}
            LIMIT %s OFFSET %s
            """,
            (product_id, limit, offset),
        )
        rows = await cur.fetchall()

        items = []
        for rr in rows:
            rid, uname, rating, title, body, created, verified = rr

            await cur.execute(
                "SELECT media_type, uri, sort_order FROM review_media WHERE review_id=%s ORDER BY sort_order ASC, id ASC",
                (rid,),
            )
            media = [{"media_type": m[0], "uri": m[1], "sort_order": int(m[2] or 0)} for m in await cur.fetchall()]

            await cur.execute(
                """
                SELECT
                  SUM(CASE WHEN is_helpful THEN 1 ELSE 0 END)::int,
                  SUM(CASE WHEN NOT is_helpful THEN 1 ELSE 0 END)::int
                FROM review_votes WHERE review_id=%s
                """,
                (rid,),
            )
            hv, nhv = await cur.fetchone()
            await cur.execute(
                "SELECT is_helpful FROM review_votes WHERE review_id=%s AND user_id=%s",
                (rid, user_id),
            )
            my = await cur.fetchone()
            my_vote = my[0] if my else None

            items.append({
                "id": int(rid),
                "user_display": uname or "User",
                "rating": int(rating),
                "title": title,
                "body": body,
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
                "is_verified_purchase": bool(verified),
                "media": media,
                "votes": {"helpful": int(hv or 0), "not_helpful": int(nhv or 0), "my_vote": my_vote},
            })

    return {"items": items, "limit": limit, "offset": offset}

@router.post("/shop/products/{product_id}/reviews")
async def upsert_product_review(product_id: int, body: ReviewIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM catalog_products WHERE id=%s", (product_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")

        if body.sku_id:
            await cur.execute("SELECT id FROM catalog_skus WHERE id=%s AND product_id=%s", (body.sku_id, product_id))
            if not await cur.fetchone():
                raise HTTPException(400, "Invalid sku_id")

        await cur.execute(
            """
            INSERT INTO item_reviews (product_id, sku_id, user_id, rating, title, body, is_verified_purchase)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (product_id, user_id) DO UPDATE SET
              sku_id=EXCLUDED.sku_id,
              rating=EXCLUDED.rating,
              title=EXCLUDED.title,
              body=EXCLUDED.body,
              is_verified_purchase=EXCLUDED.is_verified_purchase,
              created_at=now()
            RETURNING id
            """,
            (product_id, body.sku_id, user_id, body.rating, body.title, body.body, body.is_verified_purchase),
        )
        rid = int((await cur.fetchone())[0])
    return {"ok": True, "review_id": rid}

@router.post("/shop/reviews/{review_id}/vote")
async def vote_review(review_id: int, body: VoteIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM item_reviews WHERE id=%s", (review_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Review not found")

        await cur.execute(
            """
            INSERT INTO review_votes (review_id, user_id, is_helpful)
            VALUES (%s,%s,%s)
            ON CONFLICT (review_id, user_id) DO UPDATE SET
              is_helpful=EXCLUDED.is_helpful,
              created_at=now()
            """,
            (review_id, user_id, body.is_helpful),
        )
    return {"ok": True}

# --------------------------
# Store reviews
# --------------------------

class StoreReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = None
    body: Optional[str] = None

@router.get("/shop/stores/{store_id}/reviews")
async def store_reviews(store_id: int, limit: int = Query(20, ge=1, le=50), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT r.id, u.name, r.rating, r.title, r.body, r.created_at
            FROM store_reviews r
            JOIN users u ON u.id=r.user_id
            WHERE r.store_id=%s
            ORDER BY r.created_at DESC
            LIMIT %s
            """,
            (store_id, limit),
        )
        rows = await cur.fetchall()

        items = []
        for rr in rows:
            rid, uname, rating, title, body, created = rr
            await cur.execute(
                """
                SELECT
                  SUM(CASE WHEN is_helpful THEN 1 ELSE 0 END)::int,
                  SUM(CASE WHEN NOT is_helpful THEN 1 ELSE 0 END)::int
                FROM store_review_votes WHERE review_id=%s
                """,
                (rid,),
            )
            hv, nhv = await cur.fetchone()
            items.append({
                "id": int(rid),
                "user_display": uname or "User",
                "rating": int(rating),
                "title": title,
                "body": body,
                "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created),
                "votes": {"helpful": int(hv or 0), "not_helpful": int(nhv or 0)},
            })
    return {"items": items}

@router.post("/shop/stores/{store_id}/reviews")
async def upsert_store_review(store_id: int, body: StoreReviewIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM provider_stores WHERE id=%s", (store_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Store not found")

        await cur.execute(
            """
            INSERT INTO store_reviews (store_id, user_id, rating, title, body)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (store_id, user_id) DO UPDATE SET
              rating=EXCLUDED.rating,
              title=EXCLUDED.title,
              body=EXCLUDED.body,
              created_at=now()
            RETURNING id
            """,
            (store_id, user_id, body.rating, body.title, body.body),
        )
        rid = int((await cur.fetchone())[0])
    return {"ok": True, "review_id": rid}

@router.post("/shop/stores/reviews/{review_id}/vote")
async def vote_store_review(review_id: int, body: VoteIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM store_reviews WHERE id=%s", (review_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Review not found")

        await cur.execute(
            """
            INSERT INTO store_review_votes (review_id, user_id, is_helpful)
            VALUES (%s,%s,%s)
            ON CONFLICT (review_id, user_id) DO UPDATE SET
              is_helpful=EXCLUDED.is_helpful,
              created_at=now()
            """,
            (review_id, user_id, body.is_helpful),
        )
    return {"ok": True}
