# app/routers/catalog_admin.py
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Literal

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

ProviderRole = Literal["vendor", "pharmacist", "nutritionist", "hostel"]
CatalogCategory = Literal["FOOD", "ACCESSORY", "MEDICINE", "SERVICE"]
MediaType = Literal["IMAGE", "VIDEO"]
MineMode = Literal["1", "0", "all"]  # "1"=my products, "0"=global, "all"=both


# ------------------------
# Helpers
# ------------------------

async def _ensure_vendor_context(user_id: int, role: str) -> None:
    """
    Light validation: caller must have a provider store for this role.
    This keeps catalog admin "scoped" to provider-like users without user_roles table checks.
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT 1 FROM provider_stores WHERE owner_user_id=%s AND role=%s",
            (user_id, role),
        )
        if not await cur.fetchone():
            raise HTTPException(400, f"No store profile for role={role}. Complete onboarding first.")


async def _assert_owns_product(*, product_id: int, user_id: int) -> None:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM catalog_products WHERE id=%s", (product_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")

# ------------------------
# Brands (optional)
# ------------------------

class BrandIn(BaseModel):
    name: str
    about: Optional[str] = None
    logo_uri: Optional[str] = None
    website: Optional[str] = None


@router.get("/catalog/brands")
async def list_brands(user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, name, about, logo_uri, website FROM brands ORDER BY name ASC")
        rows = await cur.fetchall()
    keys = ["id", "name", "about", "logo_uri", "website"]
    return {"items": [dict(zip(keys, r)) for r in rows]}


@router.post("/catalog/brands")
async def create_brand(
    body: BrandIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    # Require provider profile so random users don't spam brands
    await _ensure_vendor_context(user_id, role)

    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name required")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO brands (name, about, logo_uri, website)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (name) DO UPDATE SET
              about=COALESCE(EXCLUDED.about, brands.about),
              logo_uri=COALESCE(EXCLUDED.logo_uri, brands.logo_uri),
              website=COALESCE(EXCLUDED.website, brands.website)
            RETURNING id
            """,
            (name, body.about, body.logo_uri, body.website),
        )
        bid = int((await cur.fetchone())[0])
    return {"ok": True, "brand_id": bid}


# ------------------------
# Products
# ------------------------

class ProductIn(BaseModel):
    category: CatalogCategory
    title: str
    short_desc: Optional[str] = None
    description: Optional[str] = None

    brand_id: Optional[int] = None
    brand_text: Optional[str] = None

    prescription_required: bool = False
    hsn_code: Optional[str] = None
    tax_class: Optional[str] = None

    variant_theme: Optional[str] = None
    is_active: bool = True


@router.get("/catalog/products")
async def list_products(
    q: Optional[str] = Query(None),
    category: Optional[CatalogCategory] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_id),
):
    where = ["p.user_id=%s"]
    params: List[object] = [user_id]

    if category:
        where.append("p.category=%s")
        params.append(category)

    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append("(p.title ILIKE %s OR p.description ILIKE %s)")
        params.extend([like, like])

    sql = f"""
    SELECT p.id, p.category, p.title,
           COALESCE(b.name, p.brand_text) AS brand,
           pm.uri AS primary_image,
           p.is_active
    FROM catalog_products p
    LEFT JOIN brands b ON b.id = p.brand_id
    LEFT JOIN LATERAL (
      SELECT uri
      FROM product_media
      WHERE product_id=p.id AND media_type='IMAGE'
      ORDER BY sort_order ASC, id ASC
      LIMIT 1
    ) pm ON TRUE
    WHERE {" AND ".join(where)}
    ORDER BY p.id DESC
    LIMIT {int(limit)} OFFSET {int(offset)}
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(sql, tuple(params))
        rows = await cur.fetchall()

    items = []
    for r in rows:
        pid, cat, title, brand, img, is_active = r
        items.append({
            "product_id": int(pid),
            "category": cat,
            "title": title,
            "brand": brand,
            "primary_image": img,
            "is_active": bool(is_active),
        })
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/catalog/products/{product_id}")
async def get_product(product_id: int, role: str = Query(...)):
    async with get_conn() as conn, conn.cursor() as cur:
        # 1) core
        await cur.execute(
            """
            SELECT id, category, brand_id, brand_text, title, short_desc, description,
                   prescription_required, hsn_code, tax_class, variant_theme, is_active
            FROM catalog_products
            WHERE id=%s
            """,
            (product_id,),
        )
        p = await cur.fetchone()
        if not p:
            raise HTTPException(404, "Product not found")

        keys = [
            "product_id",
            "category",
            "brand_id",
            "brand_text",
            "title",
            "short_desc",
            "description",
            "prescription_required",
            "hsn_code",
            "tax_class",
            "variant_theme",
            "is_active",
        ]
        product = dict(zip(keys, p))

        # 2) tags
        await cur.execute(
            "SELECT tag FROM product_tags WHERE product_id=%s ORDER BY tag ASC",
            (product_id,),
        )
        product["tags"] = [r[0] for r in (await cur.fetchall())]

        # 3) skus
        await cur.execute(
            """
            SELECT id, variant_key, variant_value, pack_label, sku_code, barcode, sort_order, is_active
            FROM catalog_skus
            WHERE product_id=%s
            ORDER BY sort_order ASC, id ASC
            """,
            (product_id,),
        )
        sku_rows = await cur.fetchall()
        product["skus"] = [
            {
                "sku_id": r[0],
                "variant_key": r[1],
                "variant_value": r[2],
                "pack_label": r[3],
                "sku_code": r[4],
                "barcode": r[5],
                "sort_order": r[6],
                "is_active": bool(r[7]),
            }
            for r in sku_rows
        ]

        # 4) media
        await cur.execute(
            """
            SELECT id, media_type, uri, label, sort_order
            FROM product_media
            WHERE product_id=%s
            ORDER BY sort_order ASC, id ASC
            """,
            (product_id,),
        )
        media_rows = await cur.fetchall()
        product["media"] = [
            {
                "id": r[0],
                "media_type": r[1],
                "uri": r[2],
                "label": r[3],
                "sort_order": r[4],
            }
            for r in media_rows
        ]

        # 5) specs
        await cur.execute(
            """
            SELECT id, spec_group, spec_key, spec_value, sort_order
            FROM product_specs
            WHERE product_id=%s
            ORDER BY spec_group ASC, sort_order ASC, id ASC
            """,
            (product_id,),
        )
        spec_rows = await cur.fetchall()
        product["specs"] = [
            {
                "id": r[0],
                "spec_group": r[1],
                "key": r[2],
                "value": r[3],
                "sort_order": r[4],
            }
            for r in spec_rows
        ]

        return {"product": product}

@router.post("/catalog/products")
async def create_product(
    body: ProductIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    if not body.title.strip():
        raise HTTPException(400, "title required")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO catalog_products
              (user_id, category, brand_id, brand_text, title, short_desc, description,
               prescription_required, hsn_code, tax_class, variant_theme, is_active)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                user_id,
                body.category, body.brand_id, body.brand_text,
                body.title.strip(), body.short_desc, body.description,
                body.prescription_required, body.hsn_code, body.tax_class,
                body.variant_theme, body.is_active
            ),
        )
        pid = int((await cur.fetchone())[0])
    return {"ok": True, "product_id": pid}


@router.patch("/catalog/products/{product_id}")
async def update_product(
    product_id: int,
    body: ProductIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE catalog_products SET
              category=%s,
              brand_id=%s,
              brand_text=%s,
              title=%s,
              short_desc=%s,
              description=%s,
              prescription_required=%s,
              hsn_code=%s,
              tax_class=%s,
              variant_theme=%s,
              is_active=%s,
              updated_at=now()
            WHERE id=%s
            RETURNING id
            """,
            (
                body.category, body.brand_id, body.brand_text,
                body.title.strip(), body.short_desc, body.description,
                body.prescription_required, body.hsn_code, body.tax_class,
                body.variant_theme, body.is_active,
                product_id
            ),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")
    return {"ok": True}


# ------------------------
# SKUs
# ------------------------

class SkuIn(BaseModel):
    variant_key: Optional[str] = None
    variant_value: Optional[str] = None
    pack_label: Optional[str] = None
    sku_code: Optional[str] = None
    barcode: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


@router.post("/catalog/products/{product_id}/skus")
async def create_sku(
    product_id: int,
    body: SkuIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO catalog_skus
              (product_id, variant_key, variant_value, pack_label, sku_code, barcode, sort_order, is_active)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (product_id, body.variant_key, body.variant_value, body.pack_label, body.sku_code, body.barcode, body.sort_order, body.is_active),
        )
        sku_id = int((await cur.fetchone())[0])
    return {"ok": True, "sku_id": sku_id}


@router.patch("/catalog/skus/{sku_id}")
async def update_sku(
    sku_id: int,
    body: SkuIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)

    # ownership check by joining sku->product
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT product_id FROM catalog_skus WHERE id=%s", (sku_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(404, "SKU not found")
        product_id = int(r[0])

    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE catalog_skus SET
              variant_key=%s,
              variant_value=%s,
              pack_label=%s,
              sku_code=%s,
              barcode=%s,
              sort_order=%s,
              is_active=%s
            WHERE id=%s
            RETURNING id
            """,
            (body.variant_key, body.variant_value, body.pack_label, body.sku_code, body.barcode, body.sort_order, body.is_active, sku_id),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "SKU not found")
    return {"ok": True}


@router.delete("/catalog/skus/{sku_id}")
async def delete_sku(
    sku_id: int,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)

    # ownership check by joining sku->product
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT product_id FROM catalog_skus WHERE id=%s", (sku_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(404, "SKU not found")
        product_id = int(r[0])

    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM catalog_skus WHERE id=%s RETURNING id", (sku_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "SKU not found")
    return {"ok": True}


# ------------------------
# Media
# ------------------------

class MediaIn(BaseModel):
    media_type: MediaType = "IMAGE"
    uri: str
    label: Optional[str] = None
    sort_order: int = 0


@router.post("/catalog/products/{product_id}/media")
async def add_media(
    product_id: int,
    body: MediaIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    await _assert_owns_product(product_id=product_id, user_id=user_id)

    if not body.uri.strip():
        raise HTTPException(400, "uri required")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO product_media (product_id, media_type, uri, label, sort_order)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (product_id, body.media_type, body.uri.strip(), body.label, body.sort_order),
        )
        mid = int((await cur.fetchone())[0])
    return {"ok": True, "media_id": mid}


@router.delete("/catalog/media/{media_id}")
async def delete_media(
    media_id: int,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)

    # ownership check by joining media->product
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT product_id FROM product_media WHERE id=%s", (media_id,))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(404, "Media not found")
        product_id = int(r[0])

    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM product_media WHERE id=%s RETURNING id", (media_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Media not found")
    return {"ok": True}


# ------------------------
# Specs (bulk replace)
# ------------------------

class SpecIn(BaseModel):
    spec_group: str = "General"
    key: str
    value: str
    sort_order: int = 0


@router.put("/catalog/products/{product_id}/specs")
async def replace_specs(
    product_id: int,
    items: List[SpecIn],
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    await _assert_owns_product(product_id=product_id, user_id=user_id)

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM product_specs WHERE product_id=%s", (product_id,))
        for it in items:
            await cur.execute(
                """
                INSERT INTO product_specs (product_id, spec_group, spec_key, spec_value, sort_order)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (product_id, it.spec_group, it.key, it.value, it.sort_order),
            )
    return {"ok": True}


# ------------------------
# Tags (bulk replace)
# ------------------------

@router.put("/catalog/products/{product_id}/tags")
async def replace_tags(
    product_id: int,
    tags: List[str],
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    await _ensure_vendor_context(user_id, role)
    await _assert_owns_product(product_id=product_id, user_id=user_id)

    tags2 = sorted({t.strip() for t in tags if t and t.strip()})
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM product_tags WHERE product_id=%s", (product_id,))
        for t in tags2:
            await cur.execute(
                "INSERT INTO product_tags (product_id, tag) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (product_id, t),
            )
    return {"ok": True}
