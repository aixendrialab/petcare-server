# app/routers/vet_schedule.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.routers.security import require_user
from app.routers.slot_settings import get_slots_for_day_internal

import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/vet/schedule",
    tags=["vet-schedule"],
    dependencies=[Depends(require_user)],
)

# ---------- Pydantic models for vet schedule ----------

class VetApptMini(BaseModel):
    id: int
    pet_id: int
    pet_name: str
    parent_name: str
    slot_id: str
    calendar_state: str
    visit_state: Optional[str] = None
    mode: Literal["in_person", "video"]


class VetSlotView(BaseModel):
    # time-of-day, not full datetime (matches parent Slot API)
    start: str          # "HH:MM"
    end: str            # "HH:MM"
    status: str         # available | full | blocked | ad_hoc | mixed
    capacity: int = 1
    booked: int = 0
    appointments: List[VetApptMini] = []


# ---------- Main endpoint: vet day schedule ----------

@router.get("/day", response_model=List[VetSlotView])
def vet_day_schedule(
    location_id: int = Query(..., description="vet_locations.id"),
    date: str = Query(..., description="YYYY-MM-DD"),
    consultation_type: Literal["in_person", "video"] = Query("in_person"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """
    For a given vet + clinic (location_id) + date, show all configured slots
    plus which ones are booked, with basic appointment details.
    """
    vet_user_id = int(user["id"])

    # Make sure this location actually belongs to this vet
    loc_row = db.execute(
        text(
            "SELECT id FROM vet_locations "
            "WHERE id = :loc AND user_id = :vet"
        ),
        {"loc": location_id, "vet": vet_user_id},
    ).first()

    if not loc_row:
        raise HTTPException(status_code=404, detail="Clinic not found for this vet")

    # ---------- 1) Base slots from slot engine ----------
    slot_setting_owner = {"id": vet_user_id}

    try:
        base_slots = get_slots_for_day_internal(
            date_str=date,
            location_id=location_id,
            consultation_type=consultation_type,
            public=False,           # vet sees everything
            db=db,
            slot_setting_owner=slot_setting_owner,
        )
    except HTTPException as exc:
        logger.warning("Slot engine error for vet schedule: %s", exc)
        base_slots = []

    slot_map: dict[tuple[str, str], VetSlotView] = {}

    for s in base_slots:
        # Slots are Pydantic models from your existing engine
        start = getattr(s, "start")
        end = getattr(s, "end")
        status = getattr(s, "status", "available")
        capacity = int(getattr(s, "capacity", 1))
        booked = int(getattr(s, "booked", 0))
        key = (start, end)

        slot_map[key] = VetSlotView(
            start=start,
            end=end,
            status=status,
            capacity=capacity,
            booked=booked,
            appointments=[],
        )

    # ---------- 2) Overlay appointments ----------
    # Use a simple day range [date 00:00, date+1 00:00)
    try:
        day_start = datetime.fromisoformat(date + "T00:00:00")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    day_end = day_start + timedelta(days=1)

    rows = db.execute(
        text(
            """
            SELECT
                a.id,
                a.pet_id,
                a.start_ts,
                a.end_ts,
                a.slot_id,
                a.mode,
                a.calendar_state,
                a.visit_state,
                p.name AS pet_name,
                u.name AS parent_name
            FROM appointments a
            JOIN pets p   ON p.id = a.pet_id
            JOIN users u  ON u.id = a.parent_id
            WHERE a.location_id = :loc
              AND a.vet_id      = :vet
              AND a.mode        = :mode
              AND a.start_ts >= :start_dt
              AND a.start_ts <  :end_dt
              AND a.calendar_state = 'ARRIVED'
            ORDER BY a.start_ts
            """
        ),
        {
            "loc": location_id,
            "vet": vet_user_id,
            "mode": consultation_type,
            "start_dt": day_start,
            "end_dt": day_end,
        },
    ).mappings().all()

    for r in rows:
        start_label = r["start_ts"].strftime("%H:%M")
        end_label = r["end_ts"].strftime("%H:%M")
        key = (start_label, end_label)

        # If appointment sits on a time that isn't in slot_settings,
        # create an ad-hoc slot so it still shows up.
        if key not in slot_map:
            slot_map[key] = VetSlotView(
                start=start_label,
                end=end_label,
                status="ad_hoc",
                capacity=1,
                booked=0,
                appointments=[],
            )

        slot = slot_map[key]
        slot.appointments.append(
            VetApptMini(
                id=r["id"],
                pet_id=r["pet_id"],
                pet_name=r["pet_name"],
                parent_name=r["parent_name"],
                slot_id=r["slot_id"],
                calendar_state=r["calendar_state"],
                visit_state=r["visit_state"],
                mode=r["mode"],
            )
        )
        slot.booked += 1

        # If capacity is known and reached, mark as full
        if slot.booked >= slot.capacity and slot.status == "available":
            slot.status = "full"

    # ---------- 3) Return ordered by start time ----------
    ordered = sorted(slot_map.values(), key=lambda s: s.start)
    return ordered
