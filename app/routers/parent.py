# app/routers/parent.py
from __future__ import annotations
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, logger, status
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.models.consult import ConsultMedication, ConsultVitals, Medication, Vitals
from app.api.models.parent import ParentProfileIn
from app.api.models.parent_consults import ParentConsultDetail, ParentRecentConsult
from app.core.db import get_conn
from app.dependencies import get_db
from .security import current_user_id, require_user
from app.routers.auth import PetsUpsert, parse_auth
from app.api.models.appointments import Appointment, AppointmentAudit, Slot
from app.api.models.prescriptions import Prescription, PrescriptionItem
from app.api.models.invoices import Invoice, InvoiceItem
from app.routers.appointments import create_appointment, AppointmentCreate


from psycopg.rows import dict_row
import json
from fastapi.encoders import jsonable_encoder

# ----------------------------------------------------------------------------
# Router setup
# ----------------------------------------------------------------------------
router = APIRouter(
    dependencies=[Depends(current_user_id)],
)

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
            SELECT 
            id, name, breed, species, dob, gender, vaccine_status, rewards, picture_uri,
            microchip, blood_group, is_neutered, allergies, chronic_conditions,
            behavior_notes, weight_kg, color_markings
            FROM pets
            WHERE user_id=%s ORDER BY id
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
                INSERT INTO pets (
                user_id, name, breed, species, dob, gender, vaccine_status, rewards, picture_uri,
                microchip, blood_group, is_neutered, allergies, chronic_conditions,
                behavior_notes, weight_kg, color_markings
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                uid, p.name, p.breed, p.species, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri,
                p.microchip, p.blood_group, p.is_neutered, p.allergies, p.chronic_conditions,
                p.behavior_notes, p.weight_kg, p.color_markings
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
            SELECT 
              id, name, breed, species, dob, gender, vaccine_status, rewards, picture_uri,
              microchip, blood_group, is_neutered, allergies, chronic_conditions,
              behavior_notes, weight_kg, color_markings
            FROM pets
            WHERE user_id=%s
            ORDER BY id
            """,
            (uid,),
        )
        pets = await cur.fetchall()

    # optional: normalize dob to ISO string if it's a date object
    for p in pets:
        if p.get("dob") is not None and hasattr(p["dob"], "isoformat"):
            p["dob"] = p["dob"].isoformat()

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
                INSERT INTO pets (user_id, name, breed, species, dob, gender, vaccine_status, rewards, picture_uri)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (uid, p.name, p.breed, p.species, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri),
            )

    return await list_pets(uid)


# app/routers/parent.py

@router.put("/pets")
async def replace_pets(payload: PetsUpsert, uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        for p in payload.pets:
            if p.id:
                await cur.execute(
                    """
                    UPDATE pets
                    SET
                      name=%s,
                      breed=%s,
                      species=%s,
                      dob=%s,
                      gender=%s,
                      vaccine_status=%s,
                      rewards=%s,
                      picture_uri=%s,
                      microchip=%s,
                      blood_group=%s,
                      is_neutered=%s,
                      allergies=%s,
                      chronic_conditions=%s,
                      behavior_notes=%s,
                      weight_kg=%s,
                      color_markings=%s
                    WHERE id=%s AND user_id=%s
                    """,
                    (
                        p.name,
                        p.breed,
                        p.species,
                        p.dob,
                        p.gender,
                        p.vaccine_status,
                        p.rewards,
                        p.picture_uri,
                        p.microchip,
                        p.blood_group,
                        p.is_neutered,
                        p.allergies,
                        p.chronic_conditions,
                        p.behavior_notes,
                        p.weight_kg,
                        p.color_markings,
                        p.id,
                        uid,
                    ),
                )
            else:
                await cur.execute(
                    """
                    INSERT INTO pets (
                      user_id, name, breed, species, dob, gender, vaccine_status, rewards, picture_uri,
                      microchip, blood_group, is_neutered, allergies, chronic_conditions,
                      behavior_notes, weight_kg, color_markings
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        uid, p.name, p.breed, p.species, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri,
                        p.microchip, p.blood_group, p.is_neutered, p.allergies, p.chronic_conditions,
                        p.behavior_notes, p.weight_kg, p.color_markings,
                    ),
                )

    return await list_pets(uid)


@router.delete("/pets/{pet_id}")
async def delete_pet(pet_id: int, uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM pets WHERE id=%s AND user_id=%s", (pet_id, uid)
        )
    return {"ok": True}

@router.get("/pets/{pet_id}")
async def get_pet(pet_id: int, uid: int = Depends(current_user_id)):
    """
    Return full pet summary for consult screen.
    This endpoint is used by vets, NOT parents.
    """
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT
                id,
                user_id,
                name,
                breed,
                species,
                dob,
                gender,
                vaccine_status,
                rewards,
                picture_uri,
                microchip,
                blood_group,
                is_neutered,
                allergies,
                chronic_conditions,
                behavior_notes,
                weight_kg,
                color_markings
            FROM pets
            WHERE id = %s
            """,
            (pet_id,),
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pet not found")

    # normalize array-like string fields
    def split_or_empty(v):
        if not v:
            return []
        return [s.strip() for s in v.split(",") if s.strip()]

    row["allergies"] = split_or_empty(row.get("allergies"))
    row["chronic_conditions"] = split_or_empty(row.get("chronic_conditions"))

    # rename keys to match frontend expectations
    return {
        "id": row["id"],
        "name": row["name"],
        "breed": row["breed"],
        "species": row["species"],
        "sex": row["gender"],
        "ageYears": None,  # frontend calculates or optional
        "avatarUrl": row["picture_uri"],

        "ownerName": "",     # parent lookup optional
        "ownerPhone": "",    # optional

        "microchip": row["microchip"],
        "blood_group": row["blood_group"],
        "allergies": row["allergies"],
        "chronicConditions": row["chronic_conditions"],
        "behaviourNotes": row["behavior_notes"],
        "weight_kg": row["weight_kg"],
        "color_markings": row["color_markings"],
    }
    
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

@router.get("/appointments/{appointment_id}")
def parent_get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    parent_id = int(user["id"])

    row = db.execute(
        text("""
            SELECT
                a.id,
                a.pet_id,
                a.parent_id,
                a.vet_id,
                p.name AS pet_name,
                vp.display_name AS vet_name,
                vl.id AS location_id,
                vl.name AS location_name,
                a.start_ts,
                a.end_ts,
                a.mode,
                a.slot_id,
                a.calendar_state,
                a.visit_state,
                a.notes
            FROM appointments a
            JOIN pets p ON p.id = a.pet_id
            LEFT JOIN vet_locations vl ON vl.id = a.location_id
            LEFT JOIN vet_profiles vp ON vp.user_id = a.vet_id
            WHERE a.id = :aid
              AND a.parent_id = :pid
            LIMIT 1
        """),
        {"aid": appointment_id, "pid": parent_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Appointment not found")

    return dict(row)

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


@router.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: int, db: Session = Depends(get_db),
    user = Depends(require_user)):
    parent_id = int(user["id"])

    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id:
        raise HTTPException(status_code=404, detail="appointment not found")
    a.calendar_state = "CANCELLED_BY_PARENT"
    db.commit()
    db.refresh(a)
    return a
    #return {"id": a.id, "calendar_state": a.calendar_state}


@router.post("/appointments/reschedule")
def parent_reschedule(
    appointment_id: int,
    new_start_ts: datetime,
    new_end_ts: datetime,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    parent_id = int(user["id"])

    # --- 1) Fetch existing appointment ---
    old = db.get(Appointment, appointment_id)
    if not old or old.parent_id != parent_id:
        raise HTTPException(404, "Appointment not found")

    # --- 2) Cancel old appointment ---
    old.calendar_state = "CANCELLED_BY_PARENT"

    # --- 3) Build new appointment payload ---
    payload = AppointmentCreate(
        vet_id = old.vet_id,
        location_id = old.location_id,
        pet_id = old.pet_id,
        mode = old.mode,
        start_ts = new_start_ts,
        end_ts = new_end_ts,
    )

    # --- 4) Call existing appointment creator ---
    new_appt = create_appointment(
        payload=payload,
        db=db,
        user=user
    )

    # --- 5) Audit trail ---
    #db.add(AppointmentAudit(
    #    appointment_id=old.id,
    #    actor_kind="parent",
    #    action="reschedule_cancel",
    #    details_json={}
    #))

    #db.add(AppointmentAudit(
    #    appointment_id=new_appt.id,
    #    actor_kind="parent",
    #    action="reschedule_create",
    #    details_json={"from_id": old.id}
    #))

    db.commit()

    return {"appt_id": new_appt.id, "slot_id": new_appt.slot_id}

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

@router.get("/consults/recent", response_model=list[ParentRecentConsult])
def get_parent_recent_consults(
    limit: int = 5,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    parent_id = int(user["id"])
    print(f"parent id {parent_id}")

    try:
        rows = db.execute(
            text("""
        SELECT
            c.id                AS consult_id,
            a.start_ts          AS date,
            p.id                AS pet_id,
            p.name              AS pet_name,
            p.picture_uri       AS pet_avatar_url,
            vl.name             AS clinic_name,
            vp.display_name     AS vet_name,
            c.diagnosis
        FROM consult c
        JOIN appointments a   ON a.id = c.appointment_id
        JOIN pets p           ON p.id = c.pet_id
        LEFT JOIN vet_locations vl ON vl.id = a.location_id
        LEFT JOIN vet_profiles  vp ON vp.user_id = c.vet_id
        WHERE a.parent_id = :pid
        ORDER BY a.start_ts DESC
        LIMIT :limit
        """),
            {"pid": parent_id, "limit": limit},
        ).mappings().all()

        # 🔍 PRINT RAW SQL ROWS
        print("➡️ Raw DB rows:", [dict(r) for r in rows])

        result = [ParentRecentConsult(**row) for row in rows]

        # 🔍 PRINT FINAL RESPONSE MODEL
        print("➡️ Response:", [r.model_dump() for r in result])

        return result

    except Exception as e:
        logger.exception("❌ Error fetching recent consults")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consults/{consult_id}", response_model=ParentConsultDetail)
def get_parent_consult_detail(
    consult_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    parent_id = int(user["id"])

    row = db.execute(
        text("""
        SELECT
            c.id               AS consult_id,
            a.id               AS appointment_id,
            a.start_ts         AS date,
            p.name             AS pet_name,
            p.picture_uri      AS pet_avatar_url,
            vl.name            AS clinic_name,
            vp.display_name    AS vet_name,
            c.reason,
            c.findings,
            c.diagnosis,
            c.advice
        FROM consult c
        JOIN appointments a   ON a.id = c.appointment_id
        JOIN pets p           ON p.id = c.pet_id
        LEFT JOIN vet_locations vl ON vl.id = a.location_id
        LEFT JOIN vet_profiles  vp ON vp.user_id = c.vet_id
        WHERE c.id = :cid
          AND a.parent_id = :pid
        """),
        {"cid": consult_id, "pid": parent_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Consult not found")

    vitals_obj = db.query(ConsultVitals).filter_by(consult_id=consult_id).first()
    meds_obj = db.query(ConsultMedication).filter_by(consult_id=consult_id).all()

    vitals = None
    if vitals_obj:
        vitals = Vitals.model_validate(vitals_obj, from_attributes=True)

    medications = [
        Medication.model_validate(m, from_attributes=True)
        for m in meds_obj
    ]

    print("➡️ Raw SELECT row:", row)

    if vitals_obj:
        print("➡️ Raw vitals ORM:", vitals_obj.__dict__)

    print("➡️ Raw medications ORM:", [m.__dict__ for m in meds_obj])

    response = ParentConsultDetail(
        consult_id=row["consult_id"],
        appointment_id=row["appointment_id"],
        date=row["date"],
        pet_name=row["pet_name"],
        pet_avatar_url=row["pet_avatar_url"],
        clinic_name=row["clinic_name"],
        vet_name=row["vet_name"],
        reason=row["reason"],
        findings=row["findings"],
        diagnosis=row["diagnosis"],
        advice=row["advice"],
        vitals=vitals,
        medications=medications
    )

    print("➡️ Final Response:", json.dumps(jsonable_encoder(response), indent=2))
    return response

@router.get("/appointments/upcoming")
def parent_upcoming_appointments(
    limit: int = 10,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    parent_id = int(user["id"])
    print("get upcoming appointments")
    rows = db.execute(
        text("""
            SELECT
                a.id,
                a.pet_id,
                a.parent_id,
                a.vet_id,
                p.name AS pet_name,
                vp.display_name AS vet_name,
                vl.id AS location_id,
                vl.name AS location_name,
                a.start_ts,
                a.end_ts,
                a.mode,
                a.slot_id,
                a.calendar_state,
                a.visit_state,
                a.mode,
                a.notes
            FROM appointments a
            JOIN pets p ON p.id = a.pet_id
            LEFT JOIN vet_locations vl ON vl.id = a.location_id
            LEFT JOIN vet_profiles vp ON vp.user_id = a.vet_id
            WHERE a.parent_id = :pid
              AND a.calendar_state = 'BOOKED'
              --AND a.start_ts >= NOW()
            ORDER BY a.start_ts ASC
            LIMIT :limit
        """),
        {"pid": parent_id, "limit": limit}
    ).mappings().all()

    return {"items": [dict(r) for r in rows]}
