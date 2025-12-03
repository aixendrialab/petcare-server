# app/routers/vet.py
from __future__ import annotations

from http.client import HTTPException
import json
from fastapi import APIRouter, Depends, Query, status
from app.core.db import get_conn
from .security import current_user_id
from app.api.models.vet import VetProfileIn
from psycopg.types.json import Json

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from decimal import Decimal
from typing import Dict, Any, Optional
from app.api.models.appointments import Appointment, AppointmentAudit, Slot
from app.api.models.invoices import Invoice, InvoiceItem
from app.api.models.prescriptions import Prescription, PrescriptionItem
from app.utils.invoice import compute_totals
from app.dependencies import get_db
from psycopg.rows import dict_row
from datetime import datetime, date, time, timedelta

router = APIRouter(dependencies=[Depends(current_user_id)])

def _to_dict(row):
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row

@router.get("/clinics/nearby")
def list_nearby_clinics(
    lat: float = Query(...),
    lng: float = Query(...),
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    Returns each vet clinic as its own row.
    Parent selects a clinic (location_id), not a vet.
    """
    rows = db.execute(text("""
SELECT 
    vl.id AS location_id,
    vl.name AS clinic_name,
    vl.line1 AS address,
    vl.city AS city,
    vl.lat,
    vl.lng,
    u.id AS vet_id,
    u.name AS vet_name,
    (
        6371 * acos(
            cos(radians(:lat)) * cos(radians(vl.lat)) *
            cos(radians(vl.lng) - radians(:lng)) +
            sin(radians(:lat)) * sin(radians(vl.lat))
        )
    ) AS distance_km
FROM vet_locations vl
JOIN users u ON u.id = vl.user_id
WHERE EXISTS (
    SELECT 1 
    FROM slot_settings ss
    WHERE ss.user_id = vl.user_id
      AND ss.location_id = vl.id
      AND ss.consultation_type = 'in_person'
      AND ss.visible_to_parents = TRUE
)
ORDER BY distance_km ASC
LIMIT :limit;
    """), {"lat": lat, "lng": lng, "limit": limit}).fetchall()


    return [dict(r._mapping) for r in rows]


@router.get("/clinics/all")
def list_all_clinics(db: Session = Depends(get_db)):
    rows = db.execute(text("""
   SELECT 
    vl.id AS id,
    vl.name AS name,
    vl.line1 AS line1,
    vl.city AS city,
    vl.lat AS lat,
    vl.lng AS lng,
    u.id AS vet_id,
    u.name AS vet_name,
    vp.display_name AS display_name
FROM vet_locations vl
JOIN users u ON u.id = vl.user_id
LEFT JOIN vet_profiles vp ON vp.user_id = u.id
WHERE EXISTS (
    SELECT 1 
    FROM slot_settings ss
    WHERE ss.user_id = vl.user_id
      AND ss.location_id = vl.id
      AND ss.consultation_type = 'in_person'
      AND ss.visible_to_parents = TRUE
)
ORDER BY vl.city, vl.name;
    """)).fetchall()


    return [dict(r._mapping) for r in rows]


def _parse_hours(hours: Optional[str]) -> Optional[tuple[time, time]]:
    """
    Simplest Hours format: '09:00-13:00' or '9-17'.
    Returns (start_time, end_time) or None if invalid.
    """
    if not hours:
        return None
    try:
        part = hours.split(",")[0].strip()  # if multiple ranges, use first
        start_s, end_s = [p.strip() for p in part.split("-")]
        if ":" not in start_s:
            start_s = f"{start_s}:00"
        if ":" not in end_s:
            end_s = f"{end_s}:00"
        h1, m1 = [int(x) for x in start_s.split(":")]
        h2, m2 = [int(x) for x in end_s.split(":")]
        return time(h1, m1), time(h2, m2)
    except Exception:
        return None
    
# helper to normalize a profile row into a proper dict with "id"
def _normalize_profile_row(row):
    if row is None:
        return None
    d = dict(row) if not isinstance(row, dict) else row
    # ensure there is a top-level "id" even if schema stores it as "user_id"
    if "id" not in d and "user_id" in d:
        d["id"] = d["user_id"]
    return d

@router.get("/profile")
async def get_profile(uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""
            SELECT u.id AS user_id, u.name, u.email, 
                   vp.legal_name, vp.display_name, vp.business_email, vp.billing_email,
                   vp.billing_address, vp.gstin, vp.pan, vp.qualifications, vp.license_no,
                   vp.experience_years, vp.specialties, vp.visit_in_clinic, vp.visit_video,
                   vp.fee_in_clinic, vp.fee_video, vp.slot_minutes
            FROM users u
            LEFT JOIN vet_profiles vp ON vp.user_id = u.id
            WHERE u.id = %s
        """, (uid,))
        prof = await cur.fetchone()

        await cur.execute(
            "SELECT * FROM vet_locations WHERE user_id = %s ORDER BY is_primary DESC, id",
            (uid,)
        )
        locs = await cur.fetchall()

    prof = _normalize_profile_row(prof)
    return {"profile": prof, "locations": locs}


@router.put("/register", status_code=status.HTTP_200_OK)
async def upsert_profile(body: VetProfileIn, uid: int = Depends(current_user_id)):
    """
    Update user + profile, replace locations, auto-create slot settings,
    then return { profile, locations }.
    """
    async with get_conn() as conn:
        # -------------------------------------------------------
        # PHASE 1 — UPDATE user, profile, locations
        # -------------------------------------------------------
        async with conn.cursor() as cur:

            # ---- Update user name/email if provided ----
            if body.name or body.email:
                sets = []
                params = []
                if body.name:
                    sets.append("name = %s")
                    params.append(body.name)
                if body.email:
                    sets.append("email = %s")
                    params.append(body.email)
                if sets:
                    params.append(uid)
                    await cur.execute(
                        f"UPDATE users SET {', '.join(sets)} WHERE id = %s",
                        tuple(params)
                    )

            # ---- Upsert vet profile ----
            await cur.execute(
                """
                INSERT INTO vet_profiles (
                    user_id, legal_name, display_name, business_email, billing_email,
                    billing_address, gstin, pan, qualifications, license_no,
                    experience_years, specialties, visit_in_clinic, visit_video,
                    fee_in_clinic, fee_video, slot_minutes
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET
                    legal_name = EXCLUDED.legal_name,
                    display_name = EXCLUDED.display_name,
                    business_email = EXCLUDED.business_email,
                    billing_email = EXCLUDED.billing_email,
                    billing_address = EXCLUDED.billing_address,
                    gstin = EXCLUDED.gstin,
                    pan = EXCLUDED.pan,
                    qualifications = EXCLUDED.qualifications,
                    license_no = EXCLUDED.license_no,
                    experience_years = EXCLUDED.experience_years,
                    specialties = EXCLUDED.specialties,
                    visit_in_clinic = EXCLUDED.visit_in_clinic,
                    visit_video = EXCLUDED.visit_video,
                    fee_in_clinic = EXCLUDED.fee_in_clinic,
                    fee_video = EXCLUDED.fee_video,
                    slot_minutes = EXCLUDED.slot_minutes
                """,
                (
                    uid,
                    body.legal_name,
                    body.display_name,
                    body.business_email,
                    body.billing_email,
                    body.billing_address,
                    body.gstin,
                    body.pan,
                    body.qualifications,
                    body.license_no,
                    body.experience_years,
                    Json(body.specialties or []),
                    body.visit_in_clinic,
                    body.visit_video,
                    body.fee_in_clinic,
                    body.fee_video,
                    body.slot_minutes,
                ),
            )

            # ---- Replace locations for the vet ----
            await cur.execute("DELETE FROM vet_locations WHERE user_id = %s", (uid,))
            for loc in (body.locations or []):
                await cur.execute(
                    """
                    INSERT INTO vet_locations
                        (user_id, name, line1, line2, city, lat, lng, hours, is_primary)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        uid,
                        loc.name,
                        loc.line1,
                        loc.line2,
                        loc.city,
                        loc.lat,
                        loc.lng,
                        loc.hours,
                        bool(loc.is_primary),
                    ),
                )

        # -------------------------------------------------------
        # PHASE 2 — AUTO-CREATE SLOT SETTINGS
        # -------------------------------------------------------
        async with conn.cursor() as cur3:

            # Fetch profile — needed for slot_minutes & visit flags
            await cur3.execute(
                """
                SELECT slot_minutes, visit_in_clinic, visit_video
                FROM vet_profiles
                WHERE user_id = %s
                """,
                (uid,)
            )
            prof = await cur3.fetchone()

            slot_minutes = prof["slot_minutes"] or 15
            supports_in_person = prof["visit_in_clinic"] == 1
            supports_video = prof["visit_video"] == 1

            # Fetch all locations for this vet
            await cur3.execute(
                "SELECT id FROM vet_locations WHERE user_id = %s ORDER BY id",
                (uid,)
            )
            locs = await cur3.fetchall()

            # Create slot settings per location
            for loc in locs:
                location_id = loc["id"]

                # ---- In-person slot settings ----
                if supports_in_person:
                    await cur3.execute(
                        """
                        INSERT INTO slot_settings (
                            user_id, location_id, consultation_type,
                            slot_minutes, gap_minutes, per_slot_capacity,
                            lead_time_minutes, booking_window_days,
                            visible_to_parents, week_rules, blackout_dates
                        )
                        VALUES (%s, %s, 'in_person',
                                %s, 0, 1,
                                0, 30,
                                FALSE, '{}', '[]')
                        ON CONFLICT (user_id, location_id, consultation_type)
                        DO NOTHING
                        """,
                        (uid, location_id, slot_minutes)
                    )

                # ---- Video slot settings ----
                if supports_video:
                    await cur3.execute(
                        """
                        INSERT INTO slot_settings (
                            user_id, location_id, consultation_type,
                            slot_minutes, gap_minutes, per_slot_capacity,
                            lead_time_minutes, booking_window_days,
                            visible_to_parents, week_rules, blackout_dates
                        )
                        VALUES (%s, NULL, 'video',
                                %s, 0, 1,
                                0, 30,
                                FALSE, '{}', '[]')
                        ON CONFLICT (user_id, location_id, consultation_type)
                        DO NOTHING
                        """,
                        (uid, slot_minutes)
                    )

        # -------------------------------------------------------
        # PHASE 3 — RETURN FRESH PROFILE + LOCATIONS
        # -------------------------------------------------------
        async with conn.cursor(row_factory=dict_row) as cur4:
            await cur4.execute("SELECT * FROM vet_profiles WHERE user_id = %s", (uid,))
            prof = await cur4.fetchone()

            await cur4.execute(
                "SELECT * FROM vet_locations WHERE user_id = %s ORDER BY is_primary DESC, id",
                (uid,)
            )
            locs = await cur4.fetchall()

    prof = _normalize_profile_row(prof)
    return {"profile": prof, "locations": locs}


from psycopg.rows import dict_row

@router.get("/locations")
async def list_locations(uid: int = Depends(current_user_id)):
    print ("in locations")
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, name FROM vet_locations WHERE user_id=%s "
            "ORDER BY is_primary DESC, id",
            (uid,),
        )
        rows = await cur.fetchall()  # -> list[dict] like [{"id":1,"name":"..."}]
    return rows


@router.get("/{vet_id}/queue")
def queue(vet_id: int) -> Dict[str, Any]:
    """
    STUB: queue is not wired yet (appointments table not present).
    Return an empty, but correctly shaped, response.
    """
    return {
        "vet_id": vet_id,
        "groups": {
            "booked": [],
            "arrived": [],
            "in_consultation": [],
            "completed": [],
        },
    }

@router.post("/{vet_id}/appointments/{appointment_id}/checkin")
def checkin(vet_id: int, appointment_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Check-in is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/start")
def start(vet_id: int, appointment_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Start consultation is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/complete")
def complete(vet_id: int, appointment_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Complete consultation is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/cancel")
def cancel(vet_id: int, appointment_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Cancel appointment is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/mark-no-show")
def no_show(vet_id: int, appointment_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Mark no-show is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/reschedule")
def vet_reschedule(vet_id: int, appointment_id: int, new_slot_id: int):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Reschedule is not implemented yet")

@router.put("/{vet_id}/appointments/{appointment_id}/prescription")
def save_rx(vet_id: int, appointment_id: int, payload: Dict[str, Any]):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Prescription flow is not implemented yet")

@router.post("/{vet_id}/appointments/{appointment_id}/invoice")
def build_invoice(vet_id: int, appointment_id: int, payload: Dict[str, Any]):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED,
                        detail="Invoice flow is not implemented yet")