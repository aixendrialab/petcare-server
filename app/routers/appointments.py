from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.dependencies import get_db
from typing import List, Literal
from pydantic import BaseModel
from app.dependencies import get_db
from app.routers.security import current_user_id, require_user
from app.routers.slot_settings import get_slots_for_day, get_slots_for_day_internal  # 👈 reuse the real engine
from app.api.models.appointments import Appointment, AppointmentCreate, AppointmentOut, Slot   # <-- full Slot model

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

@router.get("")
def list_appointments():
    return []

@router.post("", response_model=AppointmentOut)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    parent_id = int(user["id"])

    # Resolve vet_id from clinic
    row = db.execute(
        text("SELECT user_id FROM vet_locations WHERE id=:loc"),
        {"loc": payload.location_id}
    ).first()
    if not row:
        raise HTTPException(404, "Invalid clinic/location")
    vet_id = int(row[0])

    # Conflict check
    conflict = db.execute(
        text("""
            SELECT 1 FROM appointments
            WHERE location_id=:loc
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
        raise HTTPException(409, "Slot already booked")

    # Insert
    ap = Appointment(
        vet_id=vet_id,
        location_id=payload.location_id,
        parent_id=parent_id,
        pet_id=payload.pet_id,
        mode=payload.mode,
        start_ts=payload.start_ts,
        end_ts=payload.end_ts,
        slot_id=None,
        calendar_state="BOOKED"
    )
    db.add(ap)
    db.commit()
    db.refresh(ap)
    return ap


@router.post("/{appointment_id}/checkin")
def checkin(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "ARRIVED"}

@router.post("/{appointment_id}/start")
def start_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "IN_CONSULTATION"}

@router.post("/{appointment_id}/complete")
def complete_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "CONSULTATION_COMPLETE"}