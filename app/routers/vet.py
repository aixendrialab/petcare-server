# app/routers/vet.py
from __future__ import annotations

from http.client import HTTPException
import json
from fastapi import APIRouter, Depends, status
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
    # return { profile: {...}, locations: [...] } with dict rows
    async with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM vet_profiles WHERE user_id = %s", (uid,))
        prof = await cur.fetchone()
        await cur.execute(
            "SELECT * FROM vet_locations WHERE user_id = %s ORDER BY is_primary DESC, id",
            (uid,),
        )
        locs = await cur.fetchall()

    prof = _normalize_profile_row(prof)
    # locs are already list[dict] due to dict_row
    return {"profile": prof, "locations": locs}

@router.put("/register", status_code=status.HTTP_200_OK)
async def upsert_profile(body: VetProfileIn, uid: int = Depends(current_user_id)):
    """
    Updates the existing user’s name/email (created during OTP), upserts vet_profiles,
    replaces vet_locations, then returns fresh profile + locations as dicts.
    """
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            # Update user minimal fields if provided (name/email)
            if body.name or body.email:
                # set only provided fields
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
                    await cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", tuple(params))

            # Upsert profile (example upsert — keep your existing SQL here)
            await cur.execute(
                """
                INSERT INTO vet_profiles (user_id, legal_name, display_name, business_email, billing_email,
                                          billing_address, gstin, pan, qualifications, license_no,
                                          experience_years, specialties, visit_in_clinic, visit_video,
                                          fee_in_clinic, fee_video, slot_minutes)
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

            # Replace locations
            await cur.execute("DELETE FROM vet_locations WHERE user_id = %s", (uid,))
            for loc in (body.locations or []):
                await cur.execute(
                    """
                    INSERT INTO vet_locations (user_id, name, line1, line2, city, lat, lng, hours, is_primary)
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

        # Re-select using dict_row so JSON is object-shaped (not arrays)
        async with conn.cursor(row_factory=dict_row) as cur2:
            await cur2.execute("SELECT * FROM vet_profiles WHERE user_id = %s", (uid,))
            prof = await cur2.fetchone()
            await cur2.execute(
                "SELECT * FROM vet_locations WHERE user_id = %s ORDER BY is_primary DESC, id",
                (uid,),
            )
            locs = await cur2.fetchall()

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