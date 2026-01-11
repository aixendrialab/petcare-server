from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

ProviderRole = Literal["vendor", "pharmacist", "nutritionist", "hostel"]


class ProviderUpsertIn(BaseModel):
    display_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    logo_uri: Optional[str] = None
    about: Optional[str] = None

    status: Optional[str] = "ACTIVE"

    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None

    license_no: Optional[str] = None
    license_valid_till: Optional[str] = None  # YYYY-MM-DD


STORE_KEYS = [
    "id", "owner_user_id", "role", "display_name", "phone", "email", "logo_uri", "about", "status",
    "address_line1", "address_line2", "city", "state", "pincode", "license_no", "license_valid_till"
]


@router.get("/providers/me")
async def get_my_provider(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    """
    Backward compatible: returns the latest store for this role (if multiple exist).
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {",".join(STORE_KEYS)}
            FROM provider_stores
            WHERE owner_user_id=%s AND role=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, role),
        )
        row = await cur.fetchone()
        if not row:
            return {"provider": None}
        return {"provider": dict(zip(STORE_KEYS, row))}


@router.post("/providers/me")
async def upsert_my_provider(body: ProviderUpsertIn, role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    """
    Backward compatible:
    - If your DB still has UNIQUE(owner_user_id, role), this will behave as before.
    - If you remove that unique constraint, this will insert a new row each time.
    Prefer using POST /providers/stores for multi-store going forward.
    """
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO provider_stores
              (owner_user_id, role, display_name, phone, email, logo_uri, about, status,
               address_line1, address_line2, city, state, pincode,
               license_no, license_valid_till)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date)
            ON CONFLICT (owner_user_id, role) DO UPDATE SET
              display_name=EXCLUDED.display_name,
              phone=EXCLUDED.phone,
              email=EXCLUDED.email,
              logo_uri=EXCLUDED.logo_uri,
              about=EXCLUDED.about,
              status=EXCLUDED.status,
              address_line1=EXCLUDED.address_line1,
              address_line2=EXCLUDED.address_line2,
              city=EXCLUDED.city,
              state=EXCLUDED.state,
              pincode=EXCLUDED.pincode,
              license_no=EXCLUDED.license_no,
              license_valid_till=EXCLUDED.license_valid_till,
              updated_at=now()
            RETURNING id
            """,
            (
                user_id, role,
                body.display_name, body.phone, body.email, body.logo_uri, body.about, body.status,
                body.address_line1, body.address_line2, body.city, body.state, body.pincode,
                body.license_no, body.license_valid_till
            ),
        )
        store_id = int((await cur.fetchone())[0])
    return {"ok": True, "store_id": store_id}


@router.post("/providers/stores")
async def create_store(body: ProviderUpsertIn, role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    """
    ✅ Multi-store create:
    Creates a NEW store for the given role.
    Requires dropping UNIQUE(owner_user_id, role) in DB if you want true multi-store.
    """
    if not body.display_name or not body.display_name.strip():
        raise HTTPException(400, "display_name is required")

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO provider_stores
              (owner_user_id, role, display_name, phone, email, logo_uri, about, status,
               address_line1, address_line2, city, state, pincode,
               license_no, license_valid_till)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date)
            RETURNING id
            """,
            (
                user_id, role,
                body.display_name.strip(),
                body.phone, body.email, body.logo_uri, body.about, body.status,
                body.address_line1, body.address_line2, body.city, body.state, body.pincode,
                body.license_no, body.license_valid_till
            ),
        )
        store_id = int((await cur.fetchone())[0])
    return {"ok": True, "store_id": store_id}


@router.get("/providers/my-stores")
async def my_stores(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {",".join(STORE_KEYS)}
            FROM provider_stores
            WHERE owner_user_id=%s AND role=%s
            ORDER BY id DESC
            """,
            (user_id, role),
        )
        rows = await cur.fetchall()

    return {"items": [dict(zip(STORE_KEYS, r)) for r in rows]}


@router.patch("/providers/stores/{store_id}")
async def update_store(
    store_id: int,
    body: ProviderUpsertIn,
    role: ProviderRole = Query(...),
    user_id: int = Depends(current_user_id),
):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE provider_stores SET
              display_name=COALESCE(%s, display_name),
              phone=COALESCE(%s, phone),
              email=COALESCE(%s, email),
              logo_uri=COALESCE(%s, logo_uri),
              about=COALESCE(%s, about),
              status=COALESCE(%s, status),
              address_line1=COALESCE(%s, address_line1),
              address_line2=COALESCE(%s, address_line2),
              city=COALESCE(%s, city),
              state=COALESCE(%s, state),
              pincode=COALESCE(%s, pincode),
              license_no=COALESCE(%s, license_no),
              license_valid_till=COALESCE(%s::date, license_valid_till),
              updated_at=now()
            WHERE id=%s AND owner_user_id=%s AND role=%s
            RETURNING id
            """,
            (
                body.display_name, body.phone, body.email, body.logo_uri, body.about, body.status,
                body.address_line1, body.address_line2, body.city, body.state, body.pincode,
                body.license_no, body.license_valid_till,
                store_id, user_id, role
            ),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Store not found")
    return {"ok": True}
