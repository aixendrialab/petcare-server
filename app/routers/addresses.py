from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class AddressIn(BaseModel):
    label: Optional[str] = None
    recipient: str
    phone: Optional[str] = None
    line1: str
    line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    pincode: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    is_default: Optional[bool] = None

@router.get("/me/delivery-context")
async def delivery_context(user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT name FROM users WHERE id=%s", (user_id,))
        r = await cur.fetchone()
        name = (r[0] if r else None) or "You"

        await cur.execute(
            """SELECT id, label, recipient, phone, line1, line2, landmark, city, state, pincode, lat, lng, is_default
               FROM user_addresses
               WHERE user_id=%s AND is_default=TRUE
               LIMIT 1""",
            (user_id,),
        )
        a = await cur.fetchone()

    addr = None
    if a:
        keys = ["id","label","recipient","phone","line1","line2","landmark","city","state","pincode","lat","lng","is_default"]
        addr = dict(zip(keys, a))
        deliver_to_text = f"{name} • {addr['city']} • {addr['pincode']}"
    else:
        deliver_to_text = name

    return {"deliver_to_text": deliver_to_text, "default_address": addr}

@router.get("/me/addresses")
async def list_addresses(user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """SELECT id, label, recipient, phone, line1, line2, landmark, city, state, pincode, lat, lng, is_default
               FROM user_addresses
               WHERE user_id=%s
               ORDER BY is_default DESC, id DESC""",
            (user_id,),
        )
        rows = await cur.fetchall()
    keys = ["id","label","recipient","phone","line1","line2","landmark","city","state","pincode","lat","lng","is_default"]
    return {"items": [dict(zip(keys, r)) for r in rows]}

@router.post("/me/addresses")
async def create_address(body: AddressIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        # if is_default requested -> clear old default
        if body.is_default:
            await cur.execute("UPDATE user_addresses SET is_default=FALSE WHERE user_id=%s", (user_id,))

        await cur.execute(
            """INSERT INTO user_addresses
               (user_id,label,recipient,phone,line1,line2,landmark,city,state,pincode,lat,lng,is_default)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,FALSE))
               RETURNING id""",
            (user_id, body.label, body.recipient, body.phone, body.line1, body.line2, body.landmark,
             body.city, body.state, body.pincode, body.lat, body.lng, body.is_default),
        )
        addr_id = (await cur.fetchone())[0]
    return {"ok": True, "id": addr_id}

@router.patch("/me/addresses/{address_id}")
async def update_address(address_id: int, body: AddressIn, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        if body.is_default:
            await cur.execute("UPDATE user_addresses SET is_default=FALSE WHERE user_id=%s", (user_id,))

        await cur.execute(
            """UPDATE user_addresses SET
                 label=COALESCE(%s,label),
                 recipient=COALESCE(%s,recipient),
                 phone=COALESCE(%s,phone),
                 line1=COALESCE(%s,line1),
                 line2=COALESCE(%s,line2),
                 landmark=COALESCE(%s,landmark),
                 city=COALESCE(%s,city),
                 state=COALESCE(%s,state),
                 pincode=COALESCE(%s,pincode),
                 lat=COALESCE(%s,lat),
                 lng=COALESCE(%s,lng),
                 is_default=COALESCE(%s,is_default),
                 updated_at=now()
               WHERE id=%s AND user_id=%s
               RETURNING id""",
            (body.label, body.recipient, body.phone, body.line1, body.line2, body.landmark,
             body.city, body.state, body.pincode, body.lat, body.lng, body.is_default,
             address_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Address not found")
    return {"ok": True}

@router.post("/me/addresses/{address_id}/default")
async def set_default_address(address_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE user_addresses SET is_default=FALSE WHERE user_id=%s", (user_id,))
        await cur.execute(
            "UPDATE user_addresses SET is_default=TRUE, updated_at=now() WHERE id=%s AND user_id=%s RETURNING id",
            (address_id, user_id),
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Address not found")
    return {"ok": True}

@router.delete("/me/addresses/{address_id}")
async def delete_address(address_id: int, user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM user_addresses WHERE id=%s AND user_id=%s RETURNING id", (address_id, user_id))
        if not await cur.fetchone():
            raise HTTPException(404, "Address not found")
    return {"ok": True}
