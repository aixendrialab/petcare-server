# app/routers/parent.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, status
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.db import get_conn
from app.dependencies import get_db
from .security import current_user_id
from app.routers.auth import parse_auth
from app.api.models.appointments import Appointment, AppointmentAudit, Slot
from app.api.models.prescriptions import Prescription, PrescriptionItem
from app.api.models.invoices import Invoice, InvoiceItem

from psycopg.rows import dict_row

# ----------------------------------------------------------------------------
# Router setup
# ----------------------------------------------------------------------------
router = APIRouter(
    dependencies=[Depends(current_user_id)],
)

# ----------------------------------------------------------------------------
# Models (lightweight)
# ----------------------------------------------------------------------------
class ParentPetIn(BaseModel):
    name: str
    breed: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None


class ParentProfileIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    pets: list[ParentPetIn] = Field(default_factory=list)


class PetsUpsert(BaseModel):
    pets: list[ParentPetIn] = Field(default_factory=list)


# ----------------------------------------------------------------------------
# Parent Profile (async psycopg)
# ----------------------------------------------------------------------------
@router.get("/profile")
async def get_parent_profile(uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, name, email, phone FROM users WHERE id=%s", (uid,)
        )
        u = await cur.fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        await cur.execute(
            """
            SELECT id, name, breed, dob, gender, vaccine_status, rewards, picture_uri
            FROM pets WHERE user_id=%s ORDER BY id
            """,
            (uid,),
        )
        pets = await cur.fetchall()

    return {"user": u, "pets": pets}


@router.put("/profile", status_code=status.HTTP_200_OK)
async def update_parent_profile(body: ParentProfileIn, uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        # Update name/email
        await cur.execute(
            "UPDATE users SET name=%s, email=%s WHERE id=%s",
            (body.name, body.email, uid),
        )

        # Replace pets
        await cur.execute("DELETE FROM pets WHERE user_id=%s", (uid,))
        for p in body.pets or []:
            if not (p.name or "").strip():
                continue
            await cur.execute(
                """
                INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    uid,
                    p.name,
                    p.breed,
                    p.dob,
                    p.gender,
                    p.vaccine_status,
                    p.rewards,
                    p.picture_uri,
                ),
            )

    return {"ok": True}


# ----------------------------------------------------------------------------
# PETS CRUD (async psycopg)
# ----------------------------------------------------------------------------
@router.get("/pets")
async def list_pets(uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, name, breed, dob, gender, vaccine_status, rewards, picture_uri
            FROM pets WHERE user_id=%s ORDER BY id
            """,
            (uid,),
        )
        pets = await cur.fetchall()
    return {"pets": pets}


@router.post("/pets", status_code=status.HTTP_201_CREATED)
async def add_pets(body: PetsUpsert, uid: int = Depends(current_user_id)):
    pets = body.pets or []
    if not pets:
        return {"pets": []}

    async with get_conn() as conn, conn.cursor() as cur:
        for p in pets:
            await cur.execute(
                """
                INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (uid, p.name, p.breed, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri),
            )

    return await list_pets(uid)


@router.put("/pets")
async def replace_pets(body: PetsUpsert, uid: int = Depends(current_user_id)):
    new_pets = body.pets or []
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("DELETE FROM pets WHERE user_id=%s", (uid,))
        for p in new_pets:
            await cur.execute(
                """
                INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (uid, p.name, p.breed, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri),
            )

    return await list_pets(uid)


@router.delete("/pets/{pet_id}")
async def delete_pet(pet_id: int, uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM pets WHERE id=%s AND user_id=%s", (pet_id, uid)
        )
    return {"ok": True}


# ----------------------------------------------------------------------------
# Appointments (sync SQLAlchemy ORM)
# ----------------------------------------------------------------------------
@router.get("/{parent_id}/appointments")
def my_appointments(parent_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = (
        db.query(Appointment)
        .filter(Appointment.parent_id == parent_id)
        .order_by(Appointment.start_ts.desc())
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {"id": a.id, "calendar_state": a.calendar_state, "visit_state": a.visit_state}
            for a in rows
        ],
    }


@router.post("/{parent_id}/appointments")
def book(parent_id: int, slot_id: int, pet_id: int, db: Session = Depends(get_db)):
    s = db.get(Slot, slot_id)
    if not s or s.status != "OPEN":
        raise HTTPException(status_code=409, detail="slot not available")
    s.status = "BOOKED"
    a = Appointment(
        slot_id=s.id,
        vet_id=s.vet_id,
        location_id=s.location_id,
        parent_id=parent_id,
        pet_id=pet_id,
        mode=s.mode,
        start_ts=s.start_ts,
        end_ts=s.end_ts,
        calendar_state="CONFIRMED",
    )
    db.add(a)
    db.flush()
    db.add(
        AppointmentAudit(
            appointment_id=a.id,
            actor_kind="parent",
            action="book",
            details_json={"slot_id": slot_id},
        )
    )
    db.commit()
    return {"id": a.id, "calendar_state": a.calendar_state}


@router.post("/{parent_id}/appointments/{appointment_id}/cancel")
def cancel(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id:
        raise HTTPException(status_code=404, detail="appointment not found")
    a.calendar_state = "CANCELLED_BY_PARENT"
    if a.slot_id:
        s = db.get(Slot, a.slot_id)
        if s:
            s.status = "OPEN"
    db.add(
        AppointmentAudit(
            appointment_id=a.id,
            actor_kind="parent",
            action="cancel",
            details_json={},
        )
    )
    db.commit()
    return {"id": a.id, "calendar_state": a.calendar_state}


@router.post("/{parent_id}/appointments/{appointment_id}/reschedule")
def reschedule(parent_id: int, appointment_id: int, new_slot_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id:
        raise HTTPException(status_code=404, detail="appointment not found")
    ns = db.get(Slot, new_slot_id)
    if not ns or ns.status != "OPEN":
        raise HTTPException(status_code=409, detail="new slot not available")
    if a.slot_id:
        os = db.get(Slot, a.slot_id)
        if os:
            os.status = "OPEN"
    ns.status = "BOOKED"
    a.slot_id, a.start_ts, a.end_ts, a.mode, a.calendar_state = (
        ns.id,
        ns.start_ts,
        ns.end_ts,
        ns.mode,
        "CONFIRMED",
    )
    db.add(
        AppointmentAudit(
            appointment_id=a.id,
            actor_kind="parent",
            action="reschedule",
            details_json={"slot_id": new_slot_id},
        )
    )
    db.commit()
    return {"id": a.id, "calendar_state": a.calendar_state}


# ----------------------------------------------------------------------------
# Prescription / Invoice (sync)
# ----------------------------------------------------------------------------
@router.get("/{parent_id}/appointments/{appointment_id}/prescription")
def get_rx(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id:
        raise HTTPException(status_code=404, detail="appointment not found")
    rx = db.query(Prescription).filter(Prescription.appointment_id == appointment_id).one_or_none()
    if not rx:
        raise HTTPException(status_code=404, detail="not found")
    items = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id == rx.id).all()
    return {
        "diagnosis": rx.diagnosis,
        "items": [
            {
                "drug_name": i.drug_name,
                "dose": i.dose,
                "frequency": i.frequency,
                "before_after_food": i.before_after_food,
            }
            for i in items
        ],
    }


@router.get("/{parent_id}/appointments/{appointment_id}/invoice")
def get_invoice(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id:
        raise HTTPException(status_code=404, detail="appointment not found")
    inv = db.query(Invoice).filter(Invoice.appointment_id == appointment_id).one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="not found")
    items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == inv.id).all()
    return {
        "invoice_no": inv.invoice_no,
        "subtotal": str(inv.subtotal),
        "tax_cgst": str(inv.tax_cgst),
        "tax_sgst": str(inv.tax_sgst),
        "tax_igst": str(inv.tax_igst),
        "total": str(inv.total),
        "status": inv.status,
        "items": [
            {
                "description": i.description,
                "qty": float(i.qty),
                "unit_price": float(i.unit_price),
                "amount": float(i.amount),
                "tax_rate": float(i.tax_rate),
            }
            for i in items
        ],
    }


# ----------------------------------------------------------------------------
# Nearby vets (sync)
# ----------------------------------------------------------------------------
@router.get("/{parent_id}/vets/nearby")
def nearby(parent_id: int, lat: float, lng: float, limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
        SELECT vp.display_name, vl.id as location_id, vl.city, vl.lat, vl.lng,
               6371 * acos(
                 cos(radians(:lat))*cos(radians(vl.lat))*cos(radians(vl.lng)-radians(:lng)) +
                 sin(radians(:lat))*sin(radians(vl.lat))
               ) AS distance_km
        FROM vet_locations vl
        JOIN vet_profiles vp ON vp.user_id = vl.user_id
        ORDER BY distance_km ASC
        LIMIT :lim
        """
        ),
        {"lat": lat, "lng": lng, "lim": limit},
    ).fetchall()
    return {"items": [dict(r._mapping) for r in rows]}
