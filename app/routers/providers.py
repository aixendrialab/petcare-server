from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()
ProviderRole = Literal["vendor","pharmacist","nutritionist","hostel"]

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

@router.get("/providers/me")
async def get_my_provider(role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, owner_user_id, role, display_name, phone, email, logo_uri, about, status,
                      address_line1, address_line2, city, state, pincode,
                      license_no, license_valid_till
               FROM provider_stores
               WHERE owner_user_id=%s AND role=%s""",
            (user_id, role),
        )
        row = await cur.fetchone()
        if not row:
            return {"provider": None}
        keys = ["id","owner_user_id","role","display_name","phone","email","logo_uri","about","status",
                "address_line1","address_line2","city","state","pincode","license_no","license_valid_till"]
        return {"provider": dict(zip(keys, row))}

@router.post("/providers/me")
async def upsert_my_provider(body: ProviderUpsertIn, role: ProviderRole = Query(...), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO provider_stores
               (owner_user_id, role, display_name, phone, email, logo_uri, about, status,
                address_line1, address_line2, city, state, pincode,
                license_no, license_valid_till)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::date)
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
               RETURNING id""",
            (user_id, role,
             body.display_name, body.phone, body.email, body.logo_uri, body.about, body.status,
             body.address_line1, body.address_line2, body.city, body.state, body.pincode,
             body.license_no, body.license_valid_till),
        )
        store_id = int((await cur.fetchone())[0])
    return {"ok": True, "store_id": store_id}
