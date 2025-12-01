import hashlib
from fastapi import APIRouter, HTTPException, Query, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.dependencies import get_db
from typing import List, Literal
from pydantic import BaseModel
from app.dependencies import get_db
from app.routers.security import current_user_id, require_user
from app.routers.slot_settings import get_slots_for_day_internal  # 👈 reuse the real engine
from app.api.models.appointments import Appointment, AppointmentCreate, AppointmentOut, Slot   # <-- full Slot model
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(current_user_id)],
)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Simple slots API (used by your RN app)
#   GET /api/v1/appointments/slots?location_id=...&date=YYYY-MM-DD
#
#   - Uses your EXISTING slot engine in slot_settings.get_slots_for_day
#   - Forces public=True so booking rules (lead_time, blackout, visibility) apply
#   - Wraps Slot(start/end/capacity/status) → SimpleSlot(ts/date/time)
# ---------------------------------------------------------------------------

@router.get("/slots", response_model=List[Slot])
def list_simple_slots(
    location_id: int = Query(..., description="vet_locations.id"),
    date: str = Query(..., description="YYYY-MM-DD"),
    consultation_type: Literal["video", "in_person"] = Query("in_person"),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    print("📌 /appointments/slots called with parent user:", user)
    
    row = db.execute(
        text("SELECT user_id FROM vet_locations WHERE id=:loc"),
        {"loc": location_id},
    ).first()
    
    if not row:
        raise HTTPException(404, "Clinic/Location not found")
    
    vet_user_id = int(row[0])
    print("📌 Vet owner user_id =", vet_user_id)

    # Fake "vet user" object to pass to slot engine
    slot_setting_owner = {"id": vet_user_id}
                
    """
    Return simple slots for a given vet *location* and date, for the parent app.

    Uses slot_settings.get_slots_for_day with public=True.
    If there are no settings / slots, we return [] (never 404).
    """
    try:
        slots = get_slots_for_day_internal(
            date_str=date,
            location_id=location_id,
            consultation_type=consultation_type,
            public=True,
            db=db,
            slot_setting_owner=slot_setting_owner,
        )
    except HTTPException as exc:
        print("❌ Slot engine error:", exc)
        return []  # parent app: treat errors as empty list

    print(f"📌 Slots found: {len(slots)}")
    return slots   # <-- Already List[Slot], Pydantic model serializes automatically

@router.get("", response_model=list[AppointmentOut])
def list_appointments(
    mine: int = Query(0),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    parent_id = int(user["id"])

    sql = sql = """
    SELECT 
        a.id,
        a.vet_id,
        a.location_id,
        a.parent_id,
        a.pet_id,
        p.name AS pet_name,
        a.slot_id,
        a.mode,
        a.start_ts,
        a.end_ts,
        a.calendar_state,
        a.visit_state,
        a.notes,

        u.name AS vet_name,
        v.name AS location_name

    FROM appointments a
    JOIN users u ON u.id = a.vet_id
    JOIN vet_locations v ON v.id = a.location_id
    JOIN pets p ON p.id = a.pet_id

    WHERE (:mine = 0 OR a.parent_id = :parent_id)
    AND   (:status IS NULL OR a.calendar_state = :status)

    ORDER BY a.start_ts ASC
"""


    rows = db.execute(
        text(sql),
        {
            "mine": mine,
            "parent_id": parent_id,
            "status": status,
        }
    ).mappings().all()

    # rows is already dictionaries — perfect for Pydantic
    return rows


# create appointment
@router.post("", response_model=AppointmentOut)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    logger.info(f"📥 My Incoming appointment request: {payload}")

    try:
        parent_id = int(user["id"])

        # ---------------------------------------------------------
        # 1️⃣ Resolve vet_id from location (correct source of truth)
        # ---------------------------------------------------------
        row = db.execute(
            text("SELECT user_id FROM vet_locations WHERE id=:loc"),
            {"loc": payload.location_id}
        ).first()

        if not row:
            logger.error(f"❌ Invalid clinic_id={payload.location_id}")
            raise HTTPException(404, "Invalid clinic/location")

        vet_id = int(row[0])
        logger.info(f"✔ resolved vet_id={vet_id} for location={payload.location_id}")

        # ---------------------------------------------------------
        # 2️⃣ Generate secure slot token
        # ---------------------------------------------------------
        slot_id = generate_slot_token(
            vet_id,
            parent_id,
            payload.pet_id,
            payload.start_ts
        )

        # ---------------------------------------------------------
        # 3️⃣ Conflict check (overlapping slots)
        # ---------------------------------------------------------
        conflict = db.execute(
            text("""
                SELECT 1 FROM appointments
                WHERE location_id = :loc
                AND start_ts < :end
                AND end_ts > :start
            """),
            {
                "loc": payload.location_id,
                "start": payload.start_ts,
                "end": payload.end_ts
            }
        ).first()

        if conflict:
            logger.warning(
                f"⚠ Conflict: Appointment exists for {payload.start_ts}-{payload.end_ts}"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slot already booked"
            )

        # ---------------------------------------------------------
        # 4️⃣ Create appointment record
        # ---------------------------------------------------------
        appt = Appointment(
            vet_id=vet_id,
            parent_id=parent_id,
            pet_id=payload.pet_id,
            location_id=payload.location_id,
            mode=payload.mode,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            calendar_state="BOOKED",
            slot_id=slot_id,
        )

        db.add(appt)
        db.commit()
        db.refresh(appt)

        logger.info(f"✅ Appointment created id={appt.id}")

        return appt

    except SQLAlchemyError as e:
        logger.exception("❌ Database Error while booking appointment")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("❌ Unexpected Error in create_appointment")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )

def generate_slot_token(vet_id: int, location_id: int, pet_id: int, start_ts):
    return (
        f"SLT-{vet_id}-{location_id}-{pet_id}-"
        f"{start_ts.strftime('%Y%m%d')}-"
        f"{start_ts.strftime('%H%M')}"
    )

@router.post("/{appointment_id}/checkin")
def checkin(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "ARRIVED"}

@router.post("/{appointment_id}/start")
def start_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "IN_CONSULTATION"}

@router.post("/{appointment_id}/complete")
def complete_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "CONSULTATION_COMPLETE"}
