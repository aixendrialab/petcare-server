from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Literal, Dict, Any
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

Sort = Literal["recent", "price_asc", "price_desc", "rating", "popular"]

def _hero_from_sections(sections: list) -> dict | None:
    # Prefer DEALS, else TRENDING, else first section
    sec = next((s for s in sections if s.get("key") == "DEALS"), None) \
        or next((s for s in sections if s.get("key") == "TRENDING"), None) \
        or (sections[0] if sections else None)

    if not sec or not sec.get("items"):
        return None

    first = sec["items"][0]
    banner_uri = first.get("primary_image")

    title = "Today’s picks"
    subtitle = "Deals and essentials for your pet"

    if sec.get("key") == "DEALS":
        title = "Limited time deals"
        subtitle = "Best prices across stores"
    elif sec.get("key") == "TRENDING":
        title = "Trending now"
        subtitle = "Popular with pet parents this week"
    elif sec.get("key") == "FOR_YOU":
        title = "Recommended for you"
        subtitle = "Based on your browsing"

    return {
        "title": title,
        "subtitle": subtitle,
        "banner_uri": banner_uri,
        "route": "/parent/shop/list?q=deal" if sec.get("key") == "DEALS" else "/parent/shop/list",
    }

async def _product_card_rows_trending(*, limit: int):
    """
    Returns product-card rows for TRENDING in one DB query.
    Trending = most VIEW events in last 7 days.
    """
    sql = f"""
    WITH tr AS (
      SELECT e.product_id, COUNT(*)::int AS cnt
      FROM user_item_events e
      WHERE e.event_type='VIEW'
        AND e.created_at >= (now() - interval '7 days')
      GROUP BY e.product_id
      ORDER BY cnt DESC
      LIMIT {int(limit)}
    )
    SELECT
      p.id as product_id,
      p.category,
      p.title,
      COALESCE(b.name, p.brand_text) as brand,
      pm.uri as primary_image,

      -- best offer price (min active offer price across stores)
      bo.best_price,
      bo.best_mrp,
      bo.best_discount_pct,

      -- rating summary
      rv.avg_rating,
      rv.rating_count,

      -- deal badge
      CASE WHEN bo.has_deal THEN 'Deal' ELSE NULL END as badge

    FROM tr
    JOIN catalog_products p ON p.id = tr.product_id
    LEFT JOIN brands b ON b.id = p.brand_id

    LEFT JOIN LATERAL (
      SELECT uri
      FROM product_media
      WHERE product_id=p.id AND media_type='IMAGE'
      ORDER BY sort_order ASC, id ASC
      LIMIT 1
    ) pm ON TRUE

    LEFT JOIN LATERAL (
      SELECT
        MIN(so.price)::float AS best_price,
        MIN(so.mrp)::float  AS best_mrp,
        MAX(so.discount_pct)::int AS best_discount_pct,
        BOOL_OR(pt.id IS NOT NULL)::bool AS has_deal
      FROM catalog_skus sku
      JOIN store_offers so ON so.sku_id = sku.id AND so.is_active=TRUE
      LEFT JOIN promotion_targets pt ON pt.store_offer_id = so.id
      LEFT JOIN promotions pr ON pr.id = pt.promo_id AND pr.is_active=TRUE
        AND pr.valid_from <= now() AND (pr.valid_to IS NULL OR pr.valid_to >= now())
      WHERE sku.product_id = p.id AND sku.is_active=TRUE
    ) bo ON TRUE

    LEFT JOIN LATERAL (
      SELECT AVG(rating)::float AS avg_rating, COUNT(*)::int AS rating_count
      FROM item_reviews
      WHERE product_id = p.id
    ) rv ON TRUE

    WHERE p.is_active=TRUE
    ORDER BY tr.cnt DESC, p.id DESC
    """

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(sql)
        return await cur.fetchall()

async def _discount_hints_for_user(user_id: int) -> list[dict]:
    # Light-weight, deterministic, no hardcoding of products; based on cart totals
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM carts WHERE parent_user_id=%s", (user_id,))
        r = await cur.fetchone()
        if not r:
            return []

        cart_id = int(r[0])

        await cur.execute(
            """
            SELECT COALESCE(SUM(so.price * ci.qty), 0)::float
            FROM cart_items ci
            JOIN store_offers so ON so.id=ci.store_offer_id AND so.is_active=TRUE
            WHERE ci.cart_id=%s
            """,
            (cart_id,),
        )
        cart_total = float((await cur.fetchone())[0] or 0.0)

    hints: list[dict] = []

    # Example: free delivery threshold (common ecom UX)
    target = 499.0
    if cart_total < target:
        hints.append({
            "title": "Free delivery",
            "message": f"Add ₹{int(target - cart_total)} more to get free delivery on eligible items.",
            "progress": {
                "current": {"amount": round(cart_total, 2), "currency": "INR"},
                "target": {"amount": target, "currency": "INR"},
            }
        })

    # Example: “Save more with deals”
    hints.append({
        "title": "Top deals",
        "message": "Browse deals across food, toys and hygiene essentials.",
    })

    return hints

# -----------------------------
# helpers
# -----------------------------

def _money(amount: float, currency: str = "INR") -> dict:
    return {"amount": float(amount), "currency": currency or "INR"}

async def _deliver_to_text(user_id: int) -> str:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT name FROM users WHERE id=%s", (user_id,))
        r = await cur.fetchone()
        name = (r[0] if r else None) or "You"
        await cur.execute(
            """SELECT city, pincode FROM user_addresses
               WHERE user_id=%s AND is_default=TRUE LIMIT 1""",
            (user_id,),
        )
        a = await cur.fetchone()
        if a and a[0] and a[1]:
            return f"{name} • {a[0]} • {a[1]}"
        return name

async def _product_card_rows(
    *,
    where_sql: str,
    params: tuple,
    order_sql: str,
    limit: int,
    offset: int,
):
    sql = f"""
    SELECT
      p.id as product_id,
      p.category,
      p.title,
      COALESCE(b.name, p.brand_text) as brand,
      pm.uri as primary_image,

      -- best offer price (min active offer price across stores)
      bo.best_price,
      bo.best_mrp,
      bo.best_discount_pct,

      -- rating summary
      rv.avg_rating,
      rv.rating_count,

      -- deal badge if any active promo targets exist
      CASE WHEN bo.has_deal THEN 'Deal' ELSE NULL END as badge
    FROM catalog_products p
    LEFT JOIN brands b ON b.id = p.brand_id
    LEFT JOIN LATERAL (
      SELECT uri
      FROM product_media
      WHERE product_id=p.id AND media_type='IMAGE'
      ORDER BY sort_order ASC, id ASC
      LIMIT 1
    ) pm ON TRUE
    LEFT JOIN LATERAL (
      SELECT
        MIN(so.price)::float AS best_price,
        MIN(so.mrp)::float  AS best_mrp,
        MAX(so.discount_pct)::int AS best_discount_pct,
        BOOL_OR(pt.id IS NOT NULL)::bool AS has_deal
      FROM catalog_skus sku
      JOIN store_offers so ON so.sku_id = sku.id AND so.is_active=TRUE
      LEFT JOIN promotion_targets pt ON pt.store_offer_id = so.id
      LEFT JOIN promotions pr ON pr.id = pt.promo_id AND pr.is_active=TRUE
        AND pr.valid_from <= now() AND (pr.valid_to IS NULL OR pr.valid_to >= now())
      WHERE sku.product_id = p.id AND sku.is_active=TRUE
    ) bo ON TRUE
    LEFT JOIN LATERAL (
      SELECT AVG(rating)::float AS avg_rating, COUNT(*)::int AS rating_count
      FROM item_reviews
      WHERE product_id = p.id
    ) rv ON TRUE
    WHERE p.is_active=TRUE
      AND ({where_sql})
    {order_sql}
    LIMIT {int(limit)} OFFSET {int(offset)}
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()

def _order_clause(sort: Sort) -> str:
    if sort == "price_asc":
        return "ORDER BY bo.best_price NULLS LAST, p.id DESC"
    if sort == "price_desc":
        return "ORDER BY bo.best_price DESC NULLS LAST, p.id DESC"
    if sort == "rating":
        return "ORDER BY rv.avg_rating DESC NULLS LAST, rv.rating_count DESC NULLS LAST, p.id DESC"
    if sort == "popular":
        # popular = most PURCHASE events in last 30 days
        return """
        ORDER BY (
          SELECT COUNT(*) FROM user_item_events e
          WHERE e.product_id=p.id AND e.event_type='PURCHASE'
            AND e.created_at >= (now() - interval '30 days')
        ) DESC, p.id DESC
        """
    return "ORDER BY p.id DESC"

# -----------------------------
# Shop Home
# -----------------------------

@router.get("/shop/home")
async def shop_home(
    limit: int = Query(10, ge=3, le=20),          # keep small for home
    feed_limit: int = Query(24, ge=12, le=60),    # optional later
    user_id: int = Depends(current_user_id),
):
    deliver_to_text = await _deliver_to_text(user_id)

    sections: List[dict] = []

    # 1) DEALS
    deals = await _product_card_rows(
        where_sql="""EXISTS (
          SELECT 1
          FROM catalog_skus sku
          JOIN store_offers so ON so.sku_id=sku.id AND so.is_active=TRUE
          JOIN promotion_targets pt ON pt.store_offer_id=so.id
          JOIN promotions pr ON pr.id=pt.promo_id AND pr.is_active=TRUE
            AND pr.valid_from <= now() AND (pr.valid_to IS NULL OR pr.valid_to >= now())
          WHERE sku.product_id=p.id
        )""",
        params=tuple(),
        order_sql="ORDER BY p.id DESC",
        limit=limit,
        offset=0,
    )
    if deals:
        sections.append({
            "key": "DEALS",
            "title": "Deals",
            "subtitle": "Limited time offers",
            "items": _cards_from_rows(deals),
            "cta": {"title": "SEE_ALL", "route": "/parent/shop/list?deal=1"},
        })

    # 2) TRENDING (single-query helper)
    trending = await _product_card_rows_trending(limit=limit)
    if trending:
        sections.append({
            "key": "TRENDING",
            "title": "Trending",
            "subtitle": "Popular this week",
            "items": _cards_from_rows(trending),
            "cta": {"title": "SEE_ALL", "route": "/parent/shop/list?sort=popular"},
        })

    # 3) FOR_YOU (optional, only if user has viewed tags)
    tags: List[str] = []
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT pt.tag
            FROM user_item_events e
            JOIN product_tags pt ON pt.product_id = e.product_id
            WHERE e.user_id=%s AND e.event_type='VIEW'
              AND e.created_at >= (now() - interval '30 days')
            LIMIT 10
            """,
            (user_id,),
        )
        tags = [r[0] for r in await cur.fetchall()]

    if tags:
        for_you = await _product_card_rows(
            where_sql="EXISTS (SELECT 1 FROM product_tags t WHERE t.product_id=p.id AND t.tag = ANY(%s))",
            params=(tags,),
            order_sql="ORDER BY p.id DESC",
            limit=limit,
            offset=0,
        )
        if for_you:
            sections.append({
                "key": "FOR_YOU",
                "title": "For you",
                "subtitle": "Based on what you viewed",
                "items": _cards_from_rows(for_you),
                "cta": {"title": "SEE_ALL", "route": "/parent/shop/list?for_you=1"},
            })

    # 4) Fixed category shelves (fast, predictable)
    CATEGORY_SHELVES = ["FOOD", "ACCESSORY", "MEDICINE", "SERVICE"]
    for c in CATEGORY_SHELVES:
        rows = await _product_card_rows(
            where_sql="p.category=%s",
            params=(c,),
            order_sql="ORDER BY p.id DESC",
            limit=limit,
            offset=0,
        )
        if rows:
            sections.append({
                "key": c,
                "title": c.title(),
                "subtitle": None,
                "items": _cards_from_rows(rows),
                "cta": {"title": "SEE_ALL", "route": f"/parent/shop/list?category={c}"},
            })

    hero = _hero_from_sections(sections)                # should be pure logic
    discount_hints = await _discount_hints_for_user(user_id)  # keep cheap

    # OPTIONAL: cart count (so UI can show badge without extra call)
    cart_count = 0
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT COALESCE(SUM(ci.qty),0)::int
            FROM carts c
            LEFT JOIN cart_items ci ON ci.cart_id=c.id
            WHERE c.parent_user_id=%s
            """,
            (user_id,),
        )
        cart_count = int((await cur.fetchone())[0] or 0)

    return {
        "deliver_to_text": deliver_to_text,
        "hero": hero,
        "discount_hints": discount_hints,
        "sections": sections,
        "cart_count": cart_count,
    }


def _cards_from_rows(rows: list) -> list:
    out = []
    for r in rows:
        (
            product_id, category, title, brand, primary_image,
            best_price, best_mrp, best_discount_pct,
            avg_rating, rating_count,
            badge
        ) = r

        badges = []
        if badge:
            badges.append(str(badge))

        out.append({
            "product_id": int(product_id),
            "category": category,
            "title": title,
            "brand": brand,
            "primary_image": primary_image,
            "best_price": _money(best_price, "INR") if best_price is not None else None,
            "mrp": _money(best_mrp, "INR") if best_mrp is not None else None,
            "discount_pct": int(best_discount_pct) if best_discount_pct is not None else None,
            "rating_avg": float(avg_rating) if avg_rating is not None else None,
            "rating_count": int(rating_count) if rating_count is not None else None,
            "badges": badges,
        })
    return out

# -----------------------------
# Product list / search
# -----------------------------

@router.get("/shop/products")
async def list_products(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort: Sort = Query("recent"),
    limit: int = Query(24, ge=1, le=60),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_id),
):
    where = ["TRUE"]
    params: List[Any] = []

    if category:
        where.append("p.category=%s")
        params.append(category)

    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append("(p.title ILIKE %s OR p.description ILIKE %s)")
        params.extend([like, like])

    if brand and brand.strip():
        where.append("(COALESCE(b.name, p.brand_text) ILIKE %s)")
        params.append(f"%{brand.strip()}%")

    if tag and tag.strip():
        where.append("EXISTS (SELECT 1 FROM product_tags t WHERE t.product_id=p.id AND t.tag=%s)")
        params.append(tag.strip())

    # price filter via best offer
    if min_price is not None:
        where.append("bo.best_price >= %s")
        params.append(float(min_price))
    if max_price is not None:
        where.append("bo.best_price <= %s")
        params.append(float(max_price))

    rows = await _product_card_rows(
        where_sql=" AND ".join(where),
        params=tuple(params),
        order_sql=_order_clause(sort),
        limit=limit,
        offset=offset,
    )
    return {"items": _cards_from_rows(rows), "limit": limit, "offset": offset}

@router.get("/shop/feed")
async def shop_feed(
    limit: int = Query(24, ge=1, le=60),
    offset: int = Query(0, ge=0),
    exclude_ids: List[int] = Query(default=[]),
    user_id: int = Depends(current_user_id),
):
    """
    Home infinite feed.
    - Excludes already shown product ids (exclude_ids)
    - Orders by most recent products (p.id DESC)
    """
    where = ["TRUE"]
    params: List[Any] = []

    if exclude_ids:
        # PostgreSQL: p.id != ALL(array) means p.id not equal to every element
        where.append("p.id != ALL(%s)")
        params.append(exclude_ids)

    rows = await _product_card_rows(
        where_sql=" AND ".join(where),
        params=tuple(params),
        order_sql="ORDER BY p.id DESC",
        limit=limit,
        offset=offset,
    )
    return {"items": _cards_from_rows(rows), "limit": limit, "offset": offset}

# -----------------------------
# Product detail (PDP)
# -----------------------------

@router.get("/shop/products/{product_id}")
async def product_detail(
    product_id: int,
    user_id: int = Depends(current_user_id),
):
    async with get_conn() as conn, conn.cursor() as cur:
        # product core + brand + tax
        await cur.execute(
            """
            SELECT
              p.id, p.category, p.title, p.short_desc, p.description,
              p.prescription_required, p.hsn_code, p.tax_class,
              p.variant_theme,
              b.id, b.name, b.about, b.logo_uri, b.website,
              tc.gst_pct
            FROM catalog_products p
            LEFT JOIN brands b ON b.id = p.brand_id
            LEFT JOIN tax_classes tc ON tc.code = p.tax_class
            WHERE p.id=%s AND p.is_active=TRUE
            """,
            (product_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Product not found")

        (
            pid, category, title, short_desc, description,
            rx_required, hsn_code, tax_class,
            variant_theme,
            brand_id, brand_name, brand_about, brand_logo, brand_website,
            gst_pct
        ) = row

        # media
        await cur.execute(
            """SELECT media_type, uri, label, sort_order
               FROM product_media
               WHERE product_id=%s
               ORDER BY sort_order ASC, id ASC""",
            (product_id,),
        )
        media = [{"media_type": r[0], "uri": r[1], "label": r[2], "sort_order": int(r[3] or 0)} for r in await cur.fetchall()]

        # specs
        await cur.execute(
            """SELECT spec_group, spec_key, spec_value, sort_order
               FROM product_specs
               WHERE product_id=%s
               ORDER BY spec_group ASC, sort_order ASC, id ASC""",
            (product_id,),
        )
        specs = [{"spec_group": r[0], "key": r[1], "value": r[2], "sort_order": int(r[3] or 0)} for r in await cur.fetchall()]

        # tags
        await cur.execute("SELECT tag FROM product_tags WHERE product_id=%s ORDER BY tag", (product_id,))
        tags = [r[0] for r in await cur.fetchall()]

        # skus
        await cur.execute(
            """SELECT id, variant_key, variant_value, pack_label, sku_code
               FROM catalog_skus
               WHERE product_id=%s AND is_active=TRUE
               ORDER BY sort_order ASC, id ASC""",
            (product_id,),
        )
        sku_rows = await cur.fetchall()
        skus = [{
            "sku_id": int(r[0]),
            "variant_key": r[1],
            "variant_value": r[2],
            "pack_label": r[3],
            "sku_code": r[4],
        } for r in sku_rows]

        # offers: join store + badges + promos
        await cur.execute(
            """
            SELECT
              so.id as offer_id,
              so.store_id,
              ps.role,
              ps.display_name,
              ps.city, ps.state, ps.pincode,
              ps.logo_uri, ps.about,
              ps.rating_avg, ps.rating_count, ps.orders_30d,

              so.sku_id,
              so.currency,
              so.price, so.mrp, so.discount_pct,
              so.stock_qty,
              so.shipping_fee, so.eta_text, so.eta_days_min, so.eta_days_max, so.returnable, so.warranty_months
            FROM store_offers so
            JOIN provider_stores ps ON ps.id = so.store_id
            WHERE so.is_active=TRUE
              AND so.sku_id IN (SELECT id FROM catalog_skus WHERE product_id=%s AND is_active=TRUE)
              AND ps.status='ACTIVE'
            ORDER BY so.price ASC NULLS LAST, so.id DESC
            """,
            (product_id,),
        )
        offer_rows = await cur.fetchall()

        offers = []
        for r in offer_rows:
            (
                offer_id, store_id, store_role, store_name, store_city, store_state, store_pincode,
                store_logo, store_about, store_rating_avg, store_rating_count, store_orders_30d,
                sku_id,
                currency,
                price, mrp, discount_pct,
                stock_qty,
                shipping_fee, eta_text, eta_min, eta_max, returnable, warranty_months
            ) = r

            # store badges
            await cur.execute("SELECT badge FROM store_badges WHERE store_id=%s ORDER BY id", (store_id,))
            store_badges = [b[0] for b in await cur.fetchall()]

            # promotions for this offer
            await cur.execute(
                """
                SELECT pr.id, pr.title, pr.subtitle, pr.promo_type, pr.discount_pct, pr.discount_amount, pr.min_qty
                FROM promotion_targets pt
                JOIN promotions pr ON pr.id = pt.promo_id
                WHERE pt.store_offer_id=%s
                  AND pr.is_active=TRUE
                  AND pr.valid_from <= now()
                  AND (pr.valid_to IS NULL OR pr.valid_to >= now())
                ORDER BY pr.id DESC
                """,
                (offer_id,),
            )
            promo_rows = await cur.fetchall()
            promotions = []
            for pr in promo_rows:
                (pid2, ptitle, psub, ptype, dpct, damt, min_qty) = pr
                promotions.append({
                    "id": int(pid2),
                    "title": ptitle,
                    "subtitle": psub,
                    "promo_type": ptype,
                    "discount_pct": int(dpct) if dpct is not None else None,
                    "discount_amount": _money(float(damt), "INR") if damt is not None else None,
                    "min_qty": int(min_qty or 1),
                })

            offers.append({
                "offer_id": int(offer_id),
                "store": {
                    "id": int(store_id),
                    "role": store_role,
                    "display_name": store_name,
                    "city": store_city,
                    "state": store_state,
                    "pincode": store_pincode,
                    "logo_uri": store_logo,
                    "about": store_about,
                    "rating_avg": float(store_rating_avg) if store_rating_avg is not None else None,
                    "rating_count": int(store_rating_count) if store_rating_count is not None else None,
                    "orders_30d": int(store_orders_30d) if store_orders_30d is not None else None,
                    "badges": store_badges,
                },
                "sku": {"sku_id": int(sku_id)},
                "price": _money(float(price), currency),
                "mrp": _money(float(mrp), currency) if mrp is not None else None,
                "discount_pct": int(discount_pct) if discount_pct is not None else None,
                "stock_qty": int(stock_qty or 0),
                "fulfillment": {
                    "shipping_fee": _money(float(shipping_fee), currency) if shipping_fee is not None else None,
                    "eta_text": eta_text,
                    "eta_days_min": int(eta_min) if eta_min is not None else None,
                    "eta_days_max": int(eta_max) if eta_max is not None else None,
                    "returnable": bool(returnable) if returnable is not None else None,
                    "warranty_months": int(warranty_months) if warranty_months is not None else None,
                    "in_stock": (int(stock_qty or 0) > 0),
                },
                "promotions": promotions,
            })

        # review summary + previews (with media + helpful counts)
        await cur.execute(
            "SELECT COALESCE(AVG(rating),0)::float, COUNT(*)::int FROM item_reviews WHERE product_id=%s",
            (product_id,),
        )
        avg_rating, rating_count = await cur.fetchone()

        await cur.execute(
            """
            SELECT r.id, u.name, r.rating, r.title, r.body, r.created_at, r.is_verified_purchase
            FROM item_reviews r
            JOIN users u ON u.id = r.user_id
            WHERE r.product_id=%s
            ORDER BY r.created_at DESC
            LIMIT 4
            """,
            (product_id,),
        )
        review_rows = await cur.fetchall()

        review_previews = []
        for rr in review_rows:
            rid, uname, rt, rtitle, rbody, rcreated, verified = rr

            await cur.execute(
                """SELECT media_type, uri, sort_order
                   FROM review_media WHERE review_id=%s
                   ORDER BY sort_order ASC, id ASC""",
                (rid,),
            )
            media2 = [{"media_type": m[0], "uri": m[1], "sort_order": int(m[2] or 0)} for m in await cur.fetchall()]

            await cur.execute(
                """
                SELECT
                  SUM(CASE WHEN is_helpful THEN 1 ELSE 0 END)::int as helpful,
                  SUM(CASE WHEN NOT is_helpful THEN 1 ELSE 0 END)::int as not_helpful
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

            review_previews.append({
                "id": int(rid),
                "user_display": uname or "User",
                "rating": int(rt),
                "title": rtitle,
                "body": rbody,
                "created_at": rcreated.isoformat() if hasattr(rcreated, "isoformat") else str(rcreated),
                "is_verified_purchase": bool(verified),
                "media": media2,
                "votes": {"helpful": int(hv or 0), "not_helpful": int(nhv or 0), "my_vote": my_vote},
            })

        # bought_recently_label from events (purchase)
        await cur.execute(
            """
            SELECT COUNT(*)::int
            FROM user_item_events
            WHERE product_id=%s AND event_type='PURCHASE'
              AND created_at >= (now() - interval '30 days')
            """,
            (product_id,),
        )
        bought_30d = int((await cur.fetchone())[0] or 0)
        bought_recently_label = f"{bought_30d}+ bought in past month" if bought_30d > 0 else None

        # QA preview
        await cur.execute(
            """
            SELECT q.id, q.question, u.name, q.created_at
            FROM item_questions q
            JOIN users u ON u.id=q.user_id
            WHERE q.product_id=%s
            ORDER BY q.created_at DESC
            LIMIT 3
            """,
            (product_id,),
        )
        qrows = await cur.fetchall()
        qa = []
        for qid, qtext, qby, qat in qrows:
            await cur.execute(
                """
                SELECT a.id, a.answer, u.name, a.created_at
                FROM item_answers a
                JOIN users u ON u.id=a.user_id
                WHERE a.question_id=%s
                ORDER BY a.created_at DESC
                LIMIT 1
                """,
                (qid,),
            )
            ar = await cur.fetchone()
            qa.append({
                "question_id": int(qid),
                "question": qtext,
                "asked_by": qby or "User",
                "asked_at": qat.isoformat() if hasattr(qat, "isoformat") else str(qat),
                "answer_id": int(ar[0]) if ar else None,
                "answer": ar[1] if ar else None,
                "answered_by": (ar[2] if ar else None),
                "answered_at": (ar[3].isoformat() if (ar and hasattr(ar[3], "isoformat")) else (str(ar[3]) if ar else None)),
            })

        # Blocks from curated relations
        fbt = await _product_block(cur, product_id, "FBT", "Frequently bought together", 8)
        sim = await _product_block(cur, product_id, "SIMILAR", "You might also like", 12)
        also = await _product_block(cur, product_id, "ALSO_LIKE", "More to explore", 12)

        # top deals = any deal products
        top_deals = await _top_deals_block(cur, 12)

    brand = None
    if brand_id:
        brand = {"id": int(brand_id), "name": brand_name, "about": brand_about, "logo_uri": brand_logo, "website": brand_website}

    return {
        "product_id": int(pid),
        "category": category,
        "title": title,
        "short_desc": short_desc,
        "description": description,
        "brand": brand,
        "brand_text": None if brand else None,
        "tax": {"code": tax_class, "gst_pct": float(gst_pct) if gst_pct is not None else None, "hsn_code": hsn_code},
        "prescription_required": bool(rx_required),
        "variant_theme": variant_theme,
        "media": media,
        "specs": specs,
        "tags": tags,
        "skus": skus,
        "offers": offers,
        "review_summary": {"rating_avg": float(avg_rating or 0.0), "rating_count": int(rating_count or 0)},
        "review_previews": review_previews,
        "bought_recently_label": bought_recently_label,
        "qa": qa,
        "frequently_bought_together": fbt,
        "similar_products": sim,
        "more_to_explore": also,
        "top_deals": top_deals,
    }

async def _product_block(cur, product_id: int, rel_type: str, title: str, limit: int):
    """
    Build a block (FBT / SIMILAR / ALSO_LIKE) in a single query.
    Preserves ranking by item_relations.weight DESC.
    """
    sql = f"""
    WITH rel AS (
      SELECT related_product_id, weight
      FROM item_relations
      WHERE product_id=%s AND relation_type=%s
      ORDER BY weight DESC, id DESC
      LIMIT {int(limit)}
    )
    SELECT
      p.id as product_id,
      p.category,
      p.title,
      COALESCE(b.name, p.brand_text) as brand,
      pm.uri as primary_image,

      bo.best_price,
      bo.best_mrp,
      bo.best_discount_pct,

      rv.avg_rating,
      rv.rating_count,

      CASE WHEN bo.has_deal THEN 'Deal' ELSE NULL END as badge

    FROM rel
    JOIN catalog_products p ON p.id = rel.related_product_id
    LEFT JOIN brands b ON b.id = p.brand_id

    LEFT JOIN LATERAL (
      SELECT uri
      FROM product_media
      WHERE product_id=p.id AND media_type='IMAGE'
      ORDER BY sort_order ASC, id ASC
      LIMIT 1
    ) pm ON TRUE

    LEFT JOIN LATERAL (
      SELECT
        MIN(so.price)::float AS best_price,
        MIN(so.mrp)::float  AS best_mrp,
        MAX(so.discount_pct)::int AS best_discount_pct,
        BOOL_OR(pt.id IS NOT NULL)::bool AS has_deal
      FROM catalog_skus sku
      JOIN store_offers so ON so.sku_id = sku.id AND so.is_active=TRUE
      LEFT JOIN promotion_targets pt ON pt.store_offer_id = so.id
      LEFT JOIN promotions pr ON pr.id = pt.promo_id AND pr.is_active=TRUE
        AND pr.valid_from <= now() AND (pr.valid_to IS NULL OR pr.valid_to >= now())
      WHERE sku.product_id = p.id AND sku.is_active=TRUE
    ) bo ON TRUE

    LEFT JOIN LATERAL (
      SELECT AVG(rating)::float AS avg_rating, COUNT(*)::int AS rating_count
      FROM item_reviews
      WHERE product_id = p.id
    ) rv ON TRUE

    WHERE p.is_active=TRUE
    ORDER BY rel.weight DESC, p.id DESC
    """

    await cur.execute(sql, (product_id, rel_type))
    rows = await cur.fetchall()
    if not rows:
        return None

    return {"title": title, "items": _cards_from_rows(rows)}

async def _top_deals_block(cur, limit: int):
    rows = await _product_card_rows(
        where_sql="""EXISTS (
            SELECT 1
            FROM catalog_skus sku
            JOIN store_offers so ON so.sku_id=sku.id AND so.is_active=TRUE
            JOIN promotion_targets pt ON pt.store_offer_id=so.id
            JOIN promotions pr ON pr.id=pt.promo_id AND pr.is_active=TRUE
              AND pr.valid_from <= now() AND (pr.valid_to IS NULL OR pr.valid_to >= now())
            WHERE sku.product_id=p.id
        )""",
        params=tuple(),
        order_sql="ORDER BY p.id DESC",
        limit=limit,
        offset=0,
    )
    if not rows:
        return None
    return {"title": "Top deals", "items": _cards_from_rows(rows)}

# -----------------------------
# Stores
# -----------------------------

@router.get("/shop/stores/{store_id}")
async def store_page(store_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, role, display_name, phone, email, logo_uri, about, status,
                   address_line1, address_line2, city, state, pincode,
                   rating_avg, rating_count, orders_30d
            FROM provider_stores
            WHERE id=%s AND status='ACTIVE'
            """,
            (store_id,),
        )
        s = await cur.fetchone()
        if not s:
            raise HTTPException(404, "Store not found")

        await cur.execute("SELECT badge FROM store_badges WHERE store_id=%s ORDER BY id", (store_id,))
        badges = [r[0] for r in await cur.fetchall()]

        # featured offers
        await cur.execute(
            """
            SELECT so.id, so.price, so.currency, so.mrp, so.discount_pct, so.stock_qty,
                   p.id, p.title,
                   pm.uri
            FROM store_offers so
            JOIN catalog_skus sku ON sku.id=so.sku_id
            JOIN catalog_products p ON p.id=sku.product_id
            LEFT JOIN LATERAL (
              SELECT uri FROM product_media
              WHERE product_id=p.id AND media_type='IMAGE'
              ORDER BY sort_order ASC, id ASC
              LIMIT 1
            ) pm ON TRUE
            WHERE so.store_id=%s AND so.is_active=TRUE
            ORDER BY so.id DESC
            LIMIT 12
            """,
            (store_id,),
        )
        offers = []
        for r in await cur.fetchall():
            offer_id, price, currency, mrp, dpct, stock, pid, title, img = r
            offers.append({
                "offer_id": int(offer_id),
                "product_id": int(pid),
                "title": title,
                "price": _money(float(price), currency),
                "mrp": _money(float(mrp), currency) if mrp is not None else None,
                "discount_pct": int(dpct) if dpct is not None else None,
                "in_stock": (int(stock or 0) > 0),
                "primary_image": img,
            })

    keys = ["id","role","display_name","phone","email","logo_uri","about","status",
            "address_line1","address_line2","city","state","pincode","rating_avg","rating_count","orders_30d"]
    store = dict(zip(keys, s))
    store["badges"] = badges
    return {"store": store, "featured_offers": offers}

@router.get("/shop/stores/{store_id}/offers")
async def store_offers_list(
    store_id: int,
    limit: int = Query(24, ge=1, le=60),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_id),
):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT so.id, so.price, so.currency, so.mrp, so.discount_pct, so.stock_qty,
                   p.id, p.title,
                   pm.uri
            FROM store_offers so
            JOIN catalog_skus sku ON sku.id=so.sku_id
            JOIN catalog_products p ON p.id=sku.product_id
            LEFT JOIN LATERAL (
              SELECT uri FROM product_media
              WHERE product_id=p.id AND media_type='IMAGE'
              ORDER BY sort_order ASC, id ASC
              LIMIT 1
            ) pm ON TRUE
            WHERE so.store_id=%s AND so.is_active=TRUE
            ORDER BY so.id DESC
            LIMIT %s OFFSET %s
            """,
            (store_id, limit, offset),
        )
        rows = await cur.fetchall()

    items = []
    for r in rows:
        offer_id, price, currency, mrp, dpct, stock, pid, title, img = r
        items.append({
            "offer_id": int(offer_id),
            "product_id": int(pid),
            "title": title,
            "price": _money(float(price), currency),
            "mrp": _money(float(mrp), currency) if mrp is not None else None,
            "discount_pct": int(dpct) if dpct is not None else None,
            "in_stock": (int(stock or 0) > 0),
            "primary_image": img,
        })

    return {"items": items, "limit": limit, "offset": offset}

# -----------------------------
# Tags & Brands
# -----------------------------

@router.get("/shop/tags/suggest")
async def suggest_tags(q: str = Query(..., min_length=1), user_id: int = Depends(current_user_id)):
    like = f"%{q.strip()}%"
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT tag, COUNT(*)::int AS cnt
               FROM product_tags
               WHERE tag ILIKE %s
               GROUP BY tag
               ORDER BY cnt DESC, tag ASC
               LIMIT 20""",
            (like,),
        )
        rows = await cur.fetchall()
    return {"items": [{"tag": r[0], "count": int(r[1])} for r in rows]}

@router.get("/shop/brands")
async def list_brands(user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, name, about, logo_uri, website FROM brands ORDER BY name ASC")
        rows = await cur.fetchall()
    keys = ["id","name","about","logo_uri","website"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.get("/shop/brands/{brand_id}")
async def brand_detail(brand_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, name, about, logo_uri, website FROM brands WHERE id=%s", (brand_id,))
        b = await cur.fetchone()
        if not b:
            raise HTTPException(404, "Brand not found")

        # products for brand
        await cur.execute(
            "SELECT id FROM catalog_products WHERE is_active=TRUE AND brand_id=%s ORDER BY id DESC LIMIT 48",
            (brand_id,),
        )
        ids = [r[0] for r in await cur.fetchall()]

    brand_keys = ["id","name","about","logo_uri","website"]
    brand = dict(zip(brand_keys, b))

    if not ids:
        return {"brand": brand, "items": []}

    rows = await _product_card_rows(
        where_sql="p.id = ANY(%s)",
        params=(ids,),
        order_sql="ORDER BY p.id DESC",
        limit=48,
        offset=0,
    )
    return {"brand": brand, "items": _cards_from_rows(rows)}

# -----------------------------
# Events
# -----------------------------

class TrackEventIn(BaseModel):
    product_id: int
    event_type: Literal["VIEW","ADD_TO_CART","WISHLIST","PURCHASE"]
    meta: Dict[str, Any] = {}

@router.post("/shop/events")
async def track_event(body: TrackEventIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM catalog_products WHERE id=%s", (body.product_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")

        await cur.execute(
            """INSERT INTO user_item_events (user_id, product_id, event_type, meta)
               VALUES (%s,%s,%s,%s::jsonb)""",
            (user_id, body.product_id, body.event_type, json.dumps(body.meta or {})),
        )
    return {"ok": True}
