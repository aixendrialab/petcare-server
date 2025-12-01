# app/routers/slot_settings.py
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Literal, Dict, Any, Tuple, Union
from app.api.models.appointments import Slot
from app.api.models.slot_overrides import SlotOverride
from app.api.models.slot_settings import SlotSetting
from app.dependencies import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import (or_, text)
from sqlalchemy.orm import Session
from app.api.models import Base
from fastapi import Depends
from app.routers.security import require_user
from app.utils.time import now_utc, today_utc, time_after_utc


router = APIRouter(prefix="/api/v1", tags=["slots", "slot-settings"], dependencies=[Depends(require_user)])

# =============================================================================
# Pydantic models for WeekRules/DayWindow/Breaks (validated JSON shape)
# =============================================================================

class BreakWindow(BaseModel):
    """A break that disables slot generation inside a day window.
    Example:
        {"start":"10:00","end":"10:30"} -> blocks 10:00–10:30
    """
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")  # HH:MM
    end: str   = Field(..., pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def _order(self) -> "BreakWindow":
        s = datetime.strptime(self.start, "%H:%M")
        e = datetime.strptime(self.end, "%H:%M")
        if not (s < e):
            raise ValueError("break start must be before end")
        return self


class DayWindow(BaseModel):
    """An open working window for a day; can include breaks.
    Example:
        {"start":"09:00","end":"12:00",
         "breaks":[{"start":"10:00","end":"10:15"}]}
    """
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str   = Field(..., pattern=r"^\d{2}:\d{2}$")
    breaks: Optional[List[BreakWindow]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounds(self) -> "DayWindow":
        s = datetime.strptime(self.start, "%H:%M")
        e = datetime.strptime(self.end, "%H:%M")
        if not (s < e):
            raise ValueError("day window start must be before end")
        for b in self.breaks or []:
            bs = datetime.strptime(b.start, "%H:%M")
            be = datetime.strptime(b.end, "%H:%M")
            if not (bs < be):
                raise ValueError("break start must be before end")
            if not (s <= bs and be <= e):
                raise ValueError("break must lie within the day window")
        return self


class WeekRules(BaseModel):
    """Weekly template used to generate slots by weekday.
    Keys are fixed: mon..sun. Each value is a list of DayWindow.

    Example (Mon & Fri configured):
      {
        "mon":[{"start":"09:00","end":"12:00",
                "breaks":[{"start":"10:00","end":"10:30"}]}],
        "tue":[], "wed":[], "thu":[],
        "fri":[{"start":"14:00","end":"17:00"}],
        "sat":[], "sun":[]
      }
    """
    mon: List[DayWindow] = Field(default_factory=list)
    tue: List[DayWindow] = Field(default_factory=list)
    wed: List[DayWindow] = Field(default_factory=list)
    thu: List[DayWindow] = Field(default_factory=list)
    fri: List[DayWindow] = Field(default_factory=list)
    sat: List[DayWindow] = Field(default_factory=list)
    sun: List[DayWindow] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dict for JSONB storage."""
        return self.model_dump()


# =============================================================================
# Request/Response Schemas
# =============================================================================

class SlotSettingCreate(BaseModel):
    """Create/update payload for slot settings (template + knobs)."""
    #user_id: int
    location_id: Optional[int] = None  # required for in_person
    consultation_type: Literal["video", "in_person"]

    slot_minutes: int = Field(15, ge=5, le=240)
    gap_minutes: int = Field(0, ge=0, le=60)
    per_slot_capacity: int = Field(1, ge=1, le=10)
    lead_time_minutes: int = Field(0, ge=0, le=24*60)
    booking_window_days: int = Field(30, ge=1, le=365)
    visible_to_parents: bool = True

    week_rules: WeekRules
    blackout_dates: List[str] = Field(default_factory=list)

    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    @model_validator(mode="after")
    def _validate(self):
        if self.consultation_type == "in_person" and self.location_id is None:
            raise ValueError("location_id is required for in_person consultation_type")
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from must be <= effective_to")
        # if going live, require at least one weekly window
        if self.visible_to_parents:
            any_day = any(len(v or []) > 0 for v in self.week_rules.model_dump().values())
            if not any_day:
                raise ValueError("week_rules must define at least one open window before going live")
        # blackout_dates validation
        for d in self.blackout_dates:
            try: datetime.strptime(d, "%Y-%m-%d")
            except ValueError: raise ValueError("blackout_dates must be YYYY-MM-DD")
        return self


class SlotSettingRead(SlotSettingCreate):
    id: int
    class Config:
        from_attributes = True


# ----- Overrides payloads -----

class TimeRange(BaseModel):
    """A time range inside a day."""
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str   = Field(..., pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def _order(self):
        s = datetime.strptime(self.start, "%H:%M")
        e = datetime.strptime(self.end, "%H:%M")
        if not (s < e):
            raise ValueError("time range start must be before end")
        return self


class ExtraSlotRange(TimeRange):
    """Ad-hoc slots window; can adjust slot length and capacity for that window."""
    slot_minutes: Optional[int] = Field(None, ge=5, le=240)
    capacity: Optional[int] = Field(None, ge=1, le=10)


class CapacityOverrideRange(BaseModel):
    """Temporarily change capacity at a start time (point) or inside a subrange.

    Valid shapes:
      - point: {"start":"HH:MM","capacity":N}
      - range: {"start":"HH:MM","end":"HH:MM","capacity":N}
    """
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    capacity: int = Field(..., ge=1, le=10)

    @model_validator(mode="after")
    def _order(self) -> "CapacityOverrideRange":
        if self.end is None:
            return self
        s = datetime.strptime(self.start, "%H:%M")
        e = datetime.strptime(self.end, "%H:%M")
        if not (s < e):
            raise ValueError("capacity override: start must be before end")
        return self


class OverridePayload(BaseModel):
    """Per-day overrides (do not change the weekly template)."""
    open_windows: Optional[List[TimeRange]] = None
    block_windows: Optional[List[TimeRange]] = None
    extra_slots: Optional[List[ExtraSlotRange]] = None
    capacity_overrides: Optional[List[CapacityOverrideRange]] = None  # ← unchanged name, now supports point or range


class SlotOverrideUpsert(BaseModel):
    """Upsert a per-day override (merges by keys)."""
    slot_setting_id: int
    date: date
    payload: OverridePayload


class AwayUntil(BaseModel):
    """Quick helper: block a range today (e.g., vet is away)."""
    slot_setting_id: int
    date: date
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    until: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class RunningLate(BaseModel):
    """Quick helper: extend a live block when a consult overruns."""
    slot_setting_id: int
    date: date
    from_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    extra_minutes: int = Field(..., ge=1, le=180)

class SlotSegment(BaseModel):
    """Unified visual timeline segment for /slots/preview."""
    start: str
    end: str
    status: Literal["available", "blocked", "full", "break", "gap", "working"]


class UpdateSlotStatusPayload(BaseModel):
    slot_setting_id: int
    date: date
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    status: Literal["available", "blocked", "break", "working"]

class MergeWindowPayload(BaseModel):
    slot_setting_id: int
    date: str
    start: str
    end: str
    merge_time: str
    status: Literal["available", "blocked", "break", "working"]

class SplitWindowPayload(BaseModel):
    slot_setting_id: int
    date: str
    start: str
    end: str
    split_time: str
    current_status: Optional[str] = "available"
    left_status: Optional[str] = "available"
    right_status: Optional[str] = "available"

# Internal parsed types
#   ("point", start_time, capacity)
#   ("range", start_time, end_time, capacity)
ParsedOv = Union[
    Tuple[str, time, int],               # ("point", t_start, cap)
    Tuple[str, time, time, int],         # ("range", t_start, t_end, cap)
]


# =============================================================================
# Time helpers
# =============================================================================

WEEK_KEYS = ["mon","tue","wed","thu","fri","sat","sun"]

def _parse_hhmm(s: str) -> time:
    return datetime.strptime(s, "%H:%M").time()

def _format_hhmm(t: time) -> str:
    return t.strftime("%H:%M")

def _weekday_key(d: date) -> str:
    return WEEK_KEYS[d.weekday()]

def _overlaps(win: Dict[str,str], t0: time, t1: time) -> bool:
    a0, a1 = _parse_hhmm(win["start"]), _parse_hhmm(win["end"])
    return not (t1 <= a0 or t0 >= a1)

def _within(win: Dict[str,str], t0: time, t1: time) -> bool:
    ws, we = _parse_hhmm(win["start"]), _parse_hhmm(win["end"])
    return (t0 >= ws and t1 <= we)

def _time_walk(st: time, en: time, slot_min: int, gap_min: int):
    """Yield successive [start,end) pairs sized slot_min, separated by gap_min."""
    cur = datetime.combine(date.today(), st)
    end_dt = datetime.combine(date.today(), en)
    while True:
        nxt = cur + timedelta(minutes=slot_min)
        if nxt > end_dt:
            break
        yield (cur.time(), nxt.time())
        cur = nxt + timedelta(minutes=gap_min)

def _apply_breaks(slot_win: Dict[str,str], breaks: List[Dict[str,str]]) -> bool:
    """Return True if slot overlaps any break."""
    for b in breaks or []:
        if _overlaps(b, _parse_hhmm(slot_win["start"]), _parse_hhmm(slot_win["end"])):
            return True
    return False


# =============================================================================
# CRUD: SlotSettings
# =============================================================================

# --- CREATE ---
@router.post("/slot-settings", response_model=SlotSettingRead)
def create_slot_setting(
    payload: SlotSettingCreate,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """Create slot settings for the authenticated vet (user.id from token)."""
    ctx_user_id = int(user["id"])

    # (optional but recommended) ensure location belongs to this vet
    if payload.consultation_type == "in_person":
        if payload.location_id is None:
            raise HTTPException(status_code=400, detail="location_id is required for in_person")
        owns = db.execute(
            text("SELECT 1 FROM vet_locations WHERE id=:loc AND user_id=:uid"),
            {"loc": payload.location_id, "uid": ctx_user_id},
        ).first()
        if not owns:
            raise HTTPException(status_code=403, detail="location_id does not belong to you")

    # Check overlaps within same context (user, type, location)
    existing = db.query(SlotSetting).filter(
        SlotSetting.user_id == ctx_user_id,
        SlotSetting.consultation_type == payload.consultation_type,
        SlotSetting.location_id == payload.location_id,
    ).all()
    for r in existing:
        if _ranges_overlap(payload.effective_from, payload.effective_to, r.effective_from, r.effective_to):
            raise HTTPException(status_code=409, detail="Overlapping effective date ranges for the same context")

    obj = SlotSetting(
        user_id=ctx_user_id,
        **payload.model_dump()
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _ranges_overlap(a_from: Optional[date], a_to: Optional[date], b_from: Optional[date], b_to: Optional[date]) -> bool:
    """Return True if [a_from..a_to] overlaps [b_from..b_to] (None = open-ended)."""
    a_start = a_from or date.min
    a_end   = a_to   or date.max
    b_start = b_from or date.min
    b_end   = b_to   or date.max
    return not (a_end < b_start or b_end < a_start)


@router.get("/slot-settings/{setting_id}", response_model=SlotSettingRead)
def read_slot_setting(setting_id: int, db: Session = Depends(get_db)):
    """Fetch a single SlotSetting by id."""
    obj = db.get(SlotSetting, setting_id)
    if not obj: raise HTTPException(status_code=404, detail="Not found")
    return obj

# LIST by context (user + location + type)
@router.get("/slot-settings", response_model=List[SlotSettingRead])
def list_slot_settings(
    location_id: int = Query(..., description="vet_locations.id"),
    consultation_type: Literal["video", "in_person"] = Query(...),
    include_inactive: bool = Query(False, description="include rows outside effective date"),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """
    Return all SlotSetting rows for this vet, location, and type.
    If include_inactive = False, only rows whose [effective_from..effective_to] cover today are returned.
    """
    uid = int(user["id"])
    q = (
        db.query(SlotSetting)
          .filter(
              SlotSetting.user_id == uid,
              SlotSetting.location_id == location_id,
              SlotSetting.consultation_type == consultation_type,
          )
    )
    if not include_inactive:
        today = date.today()
        q = q.filter(
            or_(SlotSetting.effective_from.is_(None), SlotSetting.effective_from <= today),
            or_(SlotSetting.effective_to.is_(None),   SlotSetting.effective_to   >= today),
        )
    return q.order_by(SlotSetting.effective_from.asc().nullsfirst()).all()


# --- UPDATE ---
@router.put("/slot-settings/{setting_id}", response_model=SlotSettingRead)
def update_slot_setting(
    setting_id: int,
    payload: SlotSettingCreate,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """Update a SlotSetting owned by the authenticated vet."""
    ctx_user_id = int(user["id"])
    obj = db.get(SlotSetting, setting_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Not found")
    if obj.user_id != ctx_user_id:
        raise HTTPException(status_code=403, detail="Not your slot setting")

    if payload.consultation_type == "in_person":
        if payload.location_id is None:
            raise HTTPException(status_code=400, detail="location_id is required for in_person")
        owns = db.execute(
            text("SELECT 1 FROM vet_locations WHERE id=:loc AND user_id=:uid"),
            {"loc": payload.location_id, "uid": ctx_user_id},
        ).first()
        if not owns:
            raise HTTPException(status_code=403, detail="location_id does not belong to you")

    # overlap check against *other* rows in same context
    siblings = db.query(SlotSetting).filter(
        SlotSetting.id != setting_id,
        SlotSetting.user_id == ctx_user_id,
        SlotSetting.consultation_type == payload.consultation_type,
        SlotSetting.location_id == payload.location_id,
    ).all()
    for r in siblings:
        if _ranges_overlap(payload.effective_from, payload.effective_to, r.effective_from, r.effective_to):
            raise HTTPException(status_code=409, detail="Overlapping effective date ranges for the same context")

    for k, v in payload.model_dump().items():
        setattr(obj, k, v)

    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/slot-settings/{setting_id}")
def delete_slot_setting(setting_id: int, db: Session = Depends(get_db)):
    """Delete a SlotSetting by id."""
    obj = db.get(SlotSetting, setting_id)
    if not obj: raise HTTPException(status_code=404, detail="Not found")
    db.delete(obj); db.commit()
    return {"ok": True}


# =============================================================================
# Overrides
# =============================================================================

@router.post("/slot-settings/overrides")
def upsert_slot_override(payload: SlotOverrideUpsert, db: Session = Depends(get_db)):
    """
    Upsert a per-day override for a given slot setting.
    Behavior: merges top-level keys (open_windows, block_windows, extra_slots, capacity_overrides).
    """
    setting = db.get(SlotSetting, payload.slot_setting_id)
    if not setting: raise HTTPException(status_code=404, detail="SlotSetting not found")

    ov = (db.query(SlotOverride)
            .filter(SlotOverride.slot_setting_id == payload.slot_setting_id,
                    SlotOverride.date == payload.date)
            .first())
    incoming = payload.payload.model_dump(exclude_unset=True)
    if ov:
        merged = dict(ov.payload or {})
        for k, v in incoming.items():
            merged[k] = v
        ov.payload = merged
    else:
        ov = SlotOverride(slot_setting_id=payload.slot_setting_id, date=payload.date, payload=incoming)
        db.add(ov)
    db.commit()
    return {"ok": True, "id": ov.id}


@router.post("/slot-settings/away-until")
def away_until(payload: AwayUntil, db: Session = Depends(get_db)):
    """
    Convenience endpoint: append a block window [start, until] for the given date.
    Useful for quick 'away/meeting' actions from vet daily view.
    """
    setting = db.get(SlotSetting, payload.slot_setting_id)
    if not setting: raise HTTPException(status_code=404, detail="SlotSetting not found")

    ov = (db.query(SlotOverride)
            .filter(SlotOverride.slot_setting_id == payload.slot_setting_id,
                    SlotOverride.date == payload.date)
            .first())
    block = {"start": payload.start, "end": payload.until}
    if ov:
        ow = ov.payload or {}
        lst = list(ow.get("block_windows", []))
        lst.append(block)
        ow["block_windows"] = lst
        ov.payload = ow
    else:
        ov = SlotOverride(slot_setting_id=payload.slot_setting_id, date=payload.date,
                          payload={"block_windows": [block]})
        db.add(ov)
    db.commit()
    return {"ok": True, "id": ov.id}


@router.post("/appointments/running-late")
def running_late(payload: RunningLate, db: Session = Depends(get_db)):
    """
    Convenience endpoint: extend/append a block starting at `from_time` for `extra_minutes`.
    Typical use: a 09:40 consult is overrunning, block until 10:20 so the next slot isn’t offered.
    """
    setting = db.get(SlotSetting, payload.slot_setting_id)
    if not setting: raise HTTPException(status_code=404, detail="SlotSetting not found")

    start_dt = datetime.combine(payload.date, _parse_hhmm(payload.from_time))
    end_dt = start_dt + timedelta(minutes=payload.extra_minutes)
    block = {"start": _format_hhmm(start_dt.time()), "end": _format_hhmm(end_dt.time())}

    ov = (db.query(SlotOverride)
            .filter(SlotOverride.slot_setting_id == payload.slot_setting_id,
                    SlotOverride.date == payload.date)
            .first())
    if ov:
        ow = ov.payload or {}
        lst = list(ow.get("block_windows", []))
        lst.append(block)
        ow["block_windows"] = lst
        ov.payload = ow
    else:
        ov = SlotOverride(slot_setting_id=payload.slot_setting_id, date=payload.date,
                          payload={"block_windows": [block]})
        db.add(ov)
    db.commit()
    return {"ok": True, "id": ov.id}


# =============================================================================
# Public endpoint (refactored + fully documented)
# =============================================================================

# --- REPLACE the existing get_slots_for_day with this orchestrated, pipeline version ---
    """
    PIPELINE (pseudo-code style):
        1) day       = parse(date_str)
        2) setting   = resolveSetting(user_id, location_id, type, day)
        3) if !visibleToday(setting, day, public): return []
        4) ovp       = loadOverrides(setting.id, day)
        5) openWins  = chooseOpenWindows(setting.week_rules, ovp.open_windows, day)
        6) baseWins  = subtractBreaks(openWins)                     # <- breaks removed BEFORE slicing
        7) slots     = buildSlots(baseWins, setting.slot_minutes, setting.gap_minutes)
        8) slots     = applyBlocks(slots, ovp.block_windows)
        9) slots     = applyLeadAndCapacity(slots, setting.lead_time_minutes, ovp.capacity_overrides, public)
       10) return sort(slots)
    """
    
@router.get("/slots", response_model=List[Slot])
def get_slots_for_day(
    date_str: str = Query(..., description="YYYY-MM-DD"),
    location_id: int = Query(..., description="vet_locations.id (required for in_person; recommended for video)"),
    consultation_type: Literal["video", "in_person"] = Query(...),
    public: bool = Query(False),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    try:
        return get_slots_for_day_internal(date_str, location_id, consultation_type, public, db, user)
    except HTTPException as exc:
        raise    
            
# @router.get("/slots", response_model=List[Slot])
def get_slots_for_day_internal(
    date_str: str,
    location_id: int,
    consultation_type: Literal["video", "in_person"],
    public: bool,
    db: Session,
    slot_setting_owner,
):
    
    """Slots for the authenticated vet (user.id from token)."""
    ctx_user_id = int(slot_setting_owner["id"])
    print(f"ctx_user_id={ctx_user_id}")
    day = _parse_date_or_400(date_str)

    # pick effective setting for *this* vet
    setting = _resolve_setting_or_404(db, ctx_user_id, location_id, consultation_type, day)

    # parents see only visible & within horizon; internal sees all (blackout blocks both)
    if not _is_visible_today(setting, day, public):
        return []

    ovp = _load_override_payload(db, setting.id, day)

    # 1) open windows (override > weekly)
    open_windows = _compute_open_windows(setting, ovp, day)
    if not open_windows:
        return []

    # 2) subtract breaks
    base_windows: List[Dict[str, str]] = []
    for w in open_windows:
        base_windows.extend(_subtract_breaks_from_window(w))

    # 3) baseline slots (lead cutoff only for parents)
    lead_cutoff = _lead_cutoff_for_public(public, setting, day)
    slots = _generate_slots_from_windows(
        base_windows=base_windows,
        slot_minutes=setting.slot_minutes,
        gap_minutes=setting.gap_minutes,
        per_slot_capacity=setting.per_slot_capacity,
        lead_cutoff=lead_cutoff,
    )

    # 4) blocked windows → mark blocked
    block_windows = ovp.get("block_windows", []) or []
    if block_windows:
        for s in slots:
            t0, t1 = _parse_hhmm(s.start), _parse_hhmm(s.end)
            if any(_overlaps(bw, t0, t1) for bw in block_windows):
                s.capacity = 0
                s.status = "blocked"

    # 5) extra slots (optimistic) – honor blocks & lead cutoff
    slots.extend(_generate_extra_slots(
        extra_slots=ovp.get("extra_slots", []),
        default_slot_minutes=setting.slot_minutes,
        gap_minutes=setting.gap_minutes,
        default_capacity=setting.per_slot_capacity,
        block_windows=block_windows,
        lead_cutoff=lead_cutoff,
    ))

    # 6) capacity overrides (point or range; in-place)
    _apply_capacity_overrides_by_range(
        slots=slots,
        overrides=ovp.get("capacity_overrides", []),
    )

    # 7) parent filtering (hide blocked/zero-capacity)
    if public:
        slots = [s for s in slots if s.capacity > 0 and s.status != "blocked"]

    slots.sort(key=lambda s: s.start)
    return slots

# --- ADD these two helpers under your helpers section (e.g., after _compute_open_windows) ---

def _subtract_breaks_from_window(win: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Subtract break intervals from a working window and return **disjoint** sub-windows.

    INPUT SHAPE
      win = {
        "start": "09:00",
        "end":   "12:00",
        "breaks": [
          {"start": "10:00", "end": "10:30"},
          ...
        ]
      }

    OUTPUT SHAPE
      [
        {"start": "09:00", "end": "10:00"},
        {"start": "10:30", "end": "12:00"}
      ]

    PIPELINE (with concrete examples)
    ─────────────────────────────────
    0) Window bounds: [st, en) = [09:00, 12:00)

    1) Normalize each break to the window and drop empties
       - Clamp each break to [st, en)
       - Sort by break start time
       - Drop invalid/empty breaks (end <= start)

       Example A (clamping to bounds):
         window: [09:00, 12:00)
         raw breaks:
           [08:50, 09:10]  → clamp → [09:00, 09:10]
           [09:40, 10:15]  → stays
           [11:50, 12:10]  → clamp → [11:50, 12:00]
           [13:00, 13:10]  → clamp → [12:00, 12:00] (empty → dropped)

       After this step (sorted):
         raw_breaks = [
           [09:00, 09:10],
           [09:40, 10:15],
           [11:50, 12:00],
         ]

    2) Merge overlapping/adjacent breaks to get **merged** disjoint blocks
       - If a break starts before or exactly at the **end** of the previous merged block,
         extend the previous block’s end.
       - Else, start a new merged block.

       Example B (overlap + adjacency collapse):
         incoming (sorted):
           [10:00, 10:10], [10:10, 10:20], [10:15, 10:30]
         merged:
           [10:00, 10:30]      # because 10:10 touches 10:10 (adjacent → merge),
                              # and 10:15 is inside previous → merge/extend to 10:30

       Another Example C (no overlap):
         incoming:
           [09:05, 09:10], [09:40, 10:15], [11:50, 12:00]
         merged (unchanged):
           [09:05, 09:10], [09:40, 10:15], [11:50, 12:00]

       Visual (Example B):
         Window:  [09:00-----------------------------12:00)
                   |---- break1 ----||- br2 -||-- br3 ---|
                  10:00           10:10     10:15      10:30
         Merged:  [10:00-------------------------------10:30]

    3) Subtract the merged breaks from the window to get open sub-windows
       - Walk a cursor `cur` from `st` to `en`
       - For each merged break [bs, be):
           if cur < bs: emit [cur, bs)        # open time before the break
           cur = max(cur, be)                  # jump over the break
       - After the loop, if cur < en: emit [cur, en)

       Example D:
         window: [09:00, 12:00)
         merged breaks: [09:05, 09:10], [09:40, 10:15], [11:50, 12:00]
         subtraction result:
           [09:00, 09:05), [09:10, 09:40), [10:15, 11:50)

       Edge behavior:
         - If a break **touches** a boundary, the resulting sub-window ends/starts at that boundary.
           e.g., break [10:00, 10:30) produces ... [09:00, 10:00) and [10:30, ...)

    ASCII Timeline Cheat-Sheet
    ──────────────────────────
      09:00                                                 12:00
      |--------------------------------------------------------)
      |---- open ----|==break==|--- open ---|==brk==|-- open --|
                      10:00     10:30                 11:50 12:00

    Returns open parts only, no overlaps, no zero-length segments.
    """
    # Parse window bounds
    st = _parse_hhmm(win["start"])
    en = _parse_hhmm(win["end"])
    if en <= st:
        return []

    # 1) NORMALIZE: clamp each break to [st, en), drop empties, sort
    #    Example A: [08:50, 09:10] → [09:00, 09:10]; [13:00, 13:10] → [12:00, 12:00] (dropped)
    raw_breaks = sorted(
        [
            (max(st, _parse_hhmm(b["start"])), min(en, _parse_hhmm(b["end"])))
            for b in (win.get("breaks") or [])
        ],
        key=lambda x: x[0]
    )

    # 2) MERGE: combine overlapping or adjacent breaks into disjoint blocks
    #    Example B: [10:00,10:10],[10:10,10:20],[10:15,10:30] → [10:00,10:30]
    merged: List[tuple] = []
    for bs, be in raw_breaks:
        if be <= bs:
            # drop invalid/empty after clamping
            continue
        if not merged or bs > merged[-1][1]:
            # new disjoint block
            merged.append((bs, be))
        else:
            # overlap or adjacency: extend the last block’s end
            merged[-1] = (merged[-1][0], max(merged[-1][1], be))

    # 3) SUBTRACT: walk from st to en, skipping merged breaks
    #    Example D result: [09:00,09:05), [09:10,09:40), [10:15,11:50)
    out: List[Dict[str, str]] = []
    cur = st
    for bs, be in merged:
        if bs > cur:
            out.append({"start": _format_hhmm(cur), "end": _format_hhmm(bs)})
        cur = max(cur, be)
    if cur < en:
        out.append({"start": _format_hhmm(cur), "end": _format_hhmm(en)})

    return out


def _generate_slots_from_windows(
    base_windows: List[Dict[str, str]],
    slot_minutes: int,
    gap_minutes: int,
    per_slot_capacity: int,
    lead_cutoff: Optional[time],
) -> List[Slot]:
    """
    Slice **break-free** base windows into fixed-duration slots separated by a gap.

    INPUT
      base_windows: list of disjoint work windows, e.g.
        [{"start":"09:00","end":"10:00"}, {"start":"10:30","end":"12:00"}]
        (These are the output of _subtract_breaks_from_window; i.e., already minus breaks.)
      slot_minutes: duration of each slot (e.g., 30)
      gap_minutes : spacing between consecutive slots (e.g., 10)
      per_slot_capacity: default capacity for produced baseline slots
      lead_cutoff: if set, skip any slot whose START is before this time (same-day parent view, etc.)

    OUTPUT
      A list[Slot] like:
        [
          {"start":"09:00","end":"09:30","capacity":1,"status":"available"},
          {"start":"09:40","end":"10:10","capacity":1,"status":"available"},
          ...
        ]
      (status may be adjusted later by block/booking logic)

    HOW IT WORKS (Concrete Examples)
    ────────────────────────────────
    1) Walking a window by (slot + gap)
       We iterate with step = slot_minutes + gap_minutes. For each candidate:
         candidate = [t0, t1) where t1 = t0 + slot_minutes
         accept only if t1 <= window_end (no overrun).
         then advance t0 by step.

       Example A:
         window = [09:00, 10:00), slot=30, gap=10 → step=40
         candidates:
           [09:00, 09:30) ✓
           [09:40, 10:10) ✗  (ends after 10:00 → rejected)
         result: [09:00, 09:30)

       Example B:
         window = [10:30, 12:00), slot=30, gap=0 → step=30
         candidates:
           [10:30, 11:00) ✓
           [11:00, 11:30) ✓
           [11:30, 12:00) ✓
         result: 3 slots

       ASCII (Example B):
         10:30                    12:00
         |----30m----|----30m----|----30m----)
         ^           ^           ^
         t0          t0+30       t0+60        (gap=0 so step=30)

    2) lead_cutoff filtering (optimizes same-day bookings)
       If lead_cutoff is provided (e.g., now + lead_time),
       we SKIP any slot whose START < lead_cutoff.

       Example C:
         window = [09:00, 10:30), slot=30, gap=0
         lead_cutoff = 10:00
         candidates:
           [09:00, 09:30)  (start 09:00 < 10:00 → skip)
           [09:30, 10:00)  (start 09:30 < 10:00 → skip)
           [10:00, 10:30)  (start 10:00 ≥ cutoff → keep)
         result: [10:00, 10:30)

    3) No “tail” by design (baseline)
       If the leftover time at the end of a window is shorter than `slot_minutes`,
       we DO NOT emit a partial tail slot here (baseline policy).
       (Extra short ad-hoc windows are handled optimistically in _generate_extra_slots.)

    NOTES
      • This function only slices; it does not mark blocks or apply capacity overrides.
        Later steps can mark some slots 'blocked' or adjust capacity.
      • base_windows are assumed valid and disjoint (no breaks) to keep slicing simple.

    """
    out: List[Slot] = []

    for w in base_windows:
        ws, we = _parse_hhmm(w["start"]), _parse_hhmm(w["end"])

        # Walk by (slot + gap); _time_walk yields pairs (t0, t1) with t1 <= we
        for t0, t1 in _time_walk(ws, we, slot_minutes, gap_minutes):
            # Lead cutoff: skip slots that START before the cutoff
            if lead_cutoff and t0 < lead_cutoff:
                continue

            out.append(
                Slot(
                    start=_format_hhmm(t0),
                    end=_format_hhmm(t1),
                    capacity=per_slot_capacity,   # may be overridden later
                    # status filled later (available/blocked/full); default flows treat as available here
                )
            )

    return out


# =============================================================================
# Small, single-purpose helpers (documented)
# =============================================================================

def _parse_date_or_400(date_str: str) -> date:
    """Parse YYYY-MM-DD to date or raise HTTP 400."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")


def _resolve_setting_or_404(
    db: Session,
    user_id: int,
    location_id: int,
    consultation_type: str,
    day: date
) -> SlotSetting:
    """Return the single effective SlotSetting row for (user,location,type) on `day`, else 404/409."""
    rows = (
        db.query(SlotSetting)
          .filter(
              SlotSetting.user_id == user_id,
              SlotSetting.location_id == location_id,
              SlotSetting.consultation_type == consultation_type,
              or_(SlotSetting.effective_from.is_(None), SlotSetting.effective_from <= day),
              or_(SlotSetting.effective_to.is_(None),   SlotSetting.effective_to   >= day),
          )
          .all()
    )
    if len(rows) > 1:
        raise HTTPException(409, "Ambiguous slot settings for this user/location/type on this date")
    if not rows:
        raise HTTPException(404, "No slot settings for this user/location/type on this date")
    return rows[0]


def _is_visible_today(setting: SlotSetting, day: date, public: bool) -> bool:
    """
    Enforce blackout dates, parent visibility flag, and booking window horizon.
    - Returns False if day is a blackout.
    - Returns False for parents if not visible_to_parents.
    - Returns False for parents if outside rolling booking window.
    """
    if day.strftime("%Y-%m-%d") in (setting.blackout_dates or []):
        return False
    if public and not setting.visible_to_parents:
        return False
    if public:
        today = date.today()
        horizon = today + timedelta(days=setting.booking_window_days)
        if not (today <= day <= horizon):
            return False
    return True


def _load_override_payload(db: Session, setting_id: int, day: date) -> Dict[str, Any]:
    """Load per-date override payload for (setting_id, day); return {} if none."""
    ov = (
        db.query(SlotOverride)
          .filter(SlotOverride.slot_setting_id == setting_id, SlotOverride.date == day)
          .first()
    )
    return (ov.payload if ov else {}) or {}


def _compute_open_windows(setting: SlotSetting, ovp: Dict[str, Any], day: date) -> List[Dict[str, Any]]:
    """
    Decide the open windows for `day`: use override.open_windows if present, else weekly rules.
    Returns list of {"start","end","breaks":[...]} dicts.
    """
    if ovp.get("open_windows"):
        return [dict(w) for w in ovp["open_windows"]]

    wk = _weekday_key(day)
    rules_dict = setting.week_rules or {}
    windows = []
    for w in rules_dict.get(wk, []):
        windows.append({"start": w["start"], "end": w["end"], "breaks": w.get("breaks", [])})
    return windows


def _lead_cutoff_for_public(public: bool, setting: SlotSetting, day: date) -> Optional[time]:
    """
    Lead-time cutoff based on *UTC* 'now' and *UTC* calendar date.
    Applies only for parent/public view on the same UTC day.
    """
    if not public or not setting.lead_time_minutes:
        return None
    if day != today_utc():
        return None
    return time_after_utc(setting.lead_time_minutes)


def _generate_baseline_slots(
    base_windows: List[Dict[str, Any]],
    slot_minutes: int,
    gap_minutes: int,
    per_slot_capacity: int,
    block_windows: List[Dict[str, str]],
    breaks_in_windows: bool,
    lead_cutoff: Optional[time],
) -> List[Slot]:
    """
    Slice base windows into [slot_minutes] slots separated by [gap_minutes], honoring breaks/blocks/lead-time.
    Example (9–12 with 10:00–10:30 break, 30m slots, 10m gaps):
      -> 09:00–09:30, 09:40–10:10, (skip overlap), 10:30–11:00, 11:10–11:40
    """
    slots: List[Slot] = []
    for win in base_windows:
        st, en = _parse_hhmm(win["start"]), _parse_hhmm(win["end"])
        for t0, t1 in _time_walk(st, en, slot_minutes, gap_minutes):
            slot_dict = {"start": _format_hhmm(t0), "end": _format_hhmm(t1)}
            if breaks_in_windows and _apply_breaks(slot_dict, win.get("breaks", [])):
                continue
            if any(_overlaps(bw, t0, t1) for bw in (block_windows or [])):
                slots.append(Slot(start=slot_dict["start"], end=slot_dict["end"], capacity=0, status="blocked"))
                continue
            if lead_cutoff and t0 < lead_cutoff:
                continue
            slots.append(Slot(start=slot_dict["start"], end=slot_dict["end"], capacity=per_slot_capacity))
    return slots


def _generate_extra_slots(
    extra_slots: List[Dict[str, Any]],
    default_slot_minutes: int,
    gap_minutes: int,
    default_capacity: int,
    block_windows: List[Dict[str, str]],
    lead_cutoff: Optional[time] = None,
) -> List[Slot]:
    """
    Generate **ad-hoc** extra slots for a specific date, using an *optimistic* policy.

    GOAL
    ────
    Make short ad-hoc availability actually show up. If an extra window is shorter than the
    normal slot size, we still emit a single slot covering that small window.

    INPUT SHAPE (per item in extra_slots)
    ─────────────────────────────────────
      {
        "start": "HH:MM",
        "end"  : "HH:MM",
        # optional:
        "slot_minutes": 10,      # per-extra slicing step; defaults to default_slot_minutes
        "capacity"    : 3        # per-extra capacity; defaults to default_capacity
      }

    OUTPUT
    ──────
      A list[Slot] with each slot either 'available' (capacity>0) or 'blocked' (capacity=0)
      depending on overlap with block_windows. (Status may be further updated later.)

    RULES (with concrete examples)
    ──────────────────────────────
    1) Optimistic short window → **emit one slot**
       If window length < step (slot_minutes), we produce exactly one slot [start, end).

       Example A:
         extra window: [10:00, 10:10), default slot_minutes=30 → 10min < 30min
         result: [10:00, 10:10)  (ONE slot)

       ASCII:
         10:00        10:10
         |----- 10m -----)

    2) Normal slicing when window ≥ step
       We walk by step = slot_minutes + gap_minutes and keep candidates with t1 <= end.

       Example B:
         extra window: [11:00, 12:10), slot_minutes=20, gap=10 → step=30
         candidates:
           [11:00, 11:20) ✓
           [11:30, 11:50) ✓
           [12:00, 12:20) ✗ (overruns 12:10 → reject)
         result: [11:00, 11:20), [11:30, 11:50)

       ASCII:
         11:00                  12:10
         |--20--|--gap10--|--20--|--gap10--|--20--|
          keep                 keep                reject (ends after 12:10)

    3) lead_cutoff filter
       If lead_cutoff is provided (e.g., “now + lead_time” for parent view), skip any
       slot whose **start** < lead_cutoff.

       Example C:
         extra window: [09:05, 09:10), optimistic single slot
         lead_cutoff = 10:00 → 09:05 < 10:00 → skip (not shown to parents today)

    4) block_windows handling
       If a produced slot overlaps a block window, we keep it but mark it 'blocked'
       with capacity=0. (Staff can see it; parent view will filter blocked later.)

       Example D:
         block: [10:00, 10:10), extra short slot: [10:00, 10:10) → blocked with cap=0

    5) Capacity
       Capacity is taken from the extra payload if provided, else default_capacity.
       We do NOT clobber this later unless an explicit capacity_override applies.

    EDGE BEHAVIOR
    ─────────────
      • Invalid or zero-length windows (end <= start) are ignored.
      • If window == step exactly, it slices normally (not optimistic).
      • Half-open interval convention [start, end) avoids overlaps on touching edges.

    IMPLEMENTATION NOTES
    ────────────────────
      • We use a small inner helper `_append_slot` to centralize lead_cutoff + block checks.
      • Time arithmetic is performed on today’s date to get timedeltas; the date value itself
        is irrelevant to comparisons since we only return HH:MM strings.

    """
    out: List[Slot] = []

    def _append_slot(t0: time, t1: time, cap: int):
        # Lead time cutoff: skip early starts (typically for same-day parent view)
        if lead_cutoff and t0 < lead_cutoff:
            return
        # Blocked if overlaps any block window → visible to staff, filtered for parents later
        if any(_overlaps(bw, t0, t1) for bw in (block_windows or [])):
            out.append(Slot(start=_format_hhmm(t0), end=_format_hhmm(t1), capacity=0, status="blocked"))
        else:
            out.append(Slot(start=_format_hhmm(t0), end=_format_hhmm(t1), capacity=cap))

    for ex in extra_slots or []:
        st, en = _parse_hhmm(ex["start"]), _parse_hhmm(ex["end"])
        if en <= st:
            # Ignore invalid or zero-length windows
            continue

        # Step size for this extra window; falls back to the setting’s slot size
        step_min = int(ex.get("slot_minutes", default_slot_minutes))
        cap = int(ex.get("capacity", default_capacity))

        # Window length (minutes)
        window_min = (en.hour * 60 + en.minute) - (st.hour * 60 + st.minute)

        # (1) OPTIMISTIC: if window shorter than step → emit exactly one slot spanning it
        if window_min < step_min:
            _append_slot(st, en, cap)
            continue

        # (2) Otherwise: slice normally by step = slot_minutes + gap_minutes
        for t0, t1 in _time_walk(st, en, step_min, gap_minutes):
            _append_slot(t0, t1, cap)

    return out

def _parse_overrides_to_tuples(
    overrides: List[Dict[str, Any]],
) -> List[ParsedOv]:
    """
    Accept both shapes:
      - point: {"start":"HH:MM","capacity":N}           → open-ended from 'start' to end of day
      - range: {"start":"HH:MM","end":"HH:MM","capacity":N}  → full containment required

    Returns a list of tagged tuples, preserving input order:
      ("point", t_start, cap)
      ("range", t_start, t_end, cap)

    Skips entries missing capacity / invalid ranges / bad integers.
    """
    out: List[ParsedOv] = []
    for ov in (overrides or []):
        if "start" not in ov or "capacity" not in ov:
            continue
        try:
            cap = int(ov["capacity"])
        except Exception:
            continue

        s = _parse_hhmm(ov["start"])
        e_str = ov.get("end")

        if e_str:
            e = _parse_hhmm(e_str)
            if e <= s:
                continue  # invalid or zero-length
            out.append(("range", s, e, cap))
        else:
            out.append(("point", s, cap))
    return out

def modify_capacity_if_overridden(
    slot: Slot,
    parsed_ovs: List[ParsedOv],
) -> None:
    """
    Minimal rules (last match wins):
      • point: apply when slot.start >= override.start   (open-ended for the day)
      • range: apply when override fully contains slot [start, end)
      • Do not touch blocked slots (capacity==0 or status=='blocked').

    Containment (half-open): ov_start <= slot.start AND slot.end <= ov_end.
    """
    if slot.status == "blocked" or slot.capacity == 0:
        return

    t0 = _parse_hhmm(slot.start)
    t1 = _parse_hhmm(slot.end)

    for ov in parsed_ovs:
        kind = ov[0]
        if kind == "point":
            _, ps, cap = ov
            # Open-ended: applies to any slot starting at/after ps on this day
            if t0 >= ps:
                slot.capacity = cap  # last one wins
        else:  # "range"
            _, rs, re, cap = ov
            if rs <= t0 and t1 <= re:
                slot.capacity = cap  # last one wins

def _apply_capacity_overrides_by_range(
    slots: List[Slot],
    overrides: List[Dict[str, Any]],
) -> None:
    """
    For each slot, if encompassed by any override range, update capacity.
    No filtering. No status recalculation. The UI can grey out capacity==0.
    """
    parsed_ovs = _parse_overrides_to_tuples(overrides)
    if not parsed_ovs:
        return
    for s in slots:
        modify_capacity_if_overridden(s, parsed_ovs)

@router.get("/slots/preview", response_model=dict)
def preview_slots_for_day(
    date_str: str = Query(..., description="YYYY-MM-DD"),
    location_id: int = Query(..., description="vet_locations.id"),
    consultation_type: Literal["video", "in_person"] = Query(...),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    """
    Final deterministic algorithm:
    1️⃣ Build base segments from slot settings (A/G/I/B)
    2️⃣ Apply overrides (available, break, blocked)
    3️⃣ Merge adjacent same-status segments
    """

    ctx_user_id = int(user["id"])
    day = _parse_date_or_400(date_str)
    setting = _resolve_setting_or_404(db, ctx_user_id, location_id, consultation_type, day)
    ovp = _load_override_payload(db, setting.id, day)
    week_rules = setting.week_rules or {}
    weekday = day.strftime("%a").lower()[:3]

    # -------------------------------------------------------
    def to_min(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    def to_hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    def add_segment(segs, start, end, status):
        if to_min(end) > to_min(start):
            segs.append({"start": start, "end": end, "status": status})

    # -------------------------------------------------------
    # 1️⃣ Base segments from week rules
    day_rules = week_rules.get(weekday, [])
    segments = []
    for rule in day_rules:
        s, e = to_min(rule["start"]), to_min(rule["end"])
        cur = s
        breaks = rule.get("breaks", [])

        breaks.sort(key=lambda b: to_min(b["start"]))
        for b in breaks:
            bs, be = to_min(b["start"]), to_min(b["end"])
            if bs > cur:
                add_segment(segments, to_hhmm(cur), to_hhmm(bs), "available")
            add_segment(segments, b["start"], b["end"], "break")
            cur = be
        if cur < e:
            add_segment(segments, to_hhmm(cur), to_hhmm(e), "available")

    # -------------------------------------------------------
    # 2️⃣ Insert intra-slot gaps (slot_minutes + gap_minutes)
    with_gaps = []
    for seg in segments:
        if seg["status"] == "available" and setting.gap_minutes > 0:
            s, e = to_min(seg["start"]), to_min(seg["end"])
            sm = s
            while sm + setting.slot_minutes <= e:
                se = sm + setting.slot_minutes
                add_segment(with_gaps, to_hhmm(sm), to_hhmm(se), "available")
                sm = se
                if sm + setting.gap_minutes <= e:
                    add_segment(with_gaps, to_hhmm(sm), to_hhmm(sm + setting.gap_minutes), "gap")
                    sm += setting.gap_minutes
            if sm < e:
                add_segment(with_gaps, to_hhmm(sm), to_hhmm(e), "idle")
        else:
            with_gaps.append(seg)

    # -------------------------------------------------------
    # 3️⃣ Apply overrides (open_windows, break_windows, block_windows)
    def apply_overrides(base, overrides, override_status):
        result = []
        for seg in base:
            s1, e1 = to_min(seg["start"]), to_min(seg["end"])
            overlapped = False
            for o in overrides:
                s2, e2 = to_min(o["start"]), to_min(o["end"])
                if e2 <= s1 or s2 >= e1:
                    continue
                overlapped = True
                if s2 > s1:
                    add_segment(result, to_hhmm(s1), to_hhmm(s2), seg["status"])
                add_segment(result, to_hhmm(max(s1, s2)), to_hhmm(min(e1, e2)), override_status)
                if e2 < e1:
                    add_segment(result, to_hhmm(e2), to_hhmm(e1), seg["status"])
            if not overlapped:
                result.append(seg)

        if base:
            base_start, base_end = to_min(base[0]["start"]), to_min(base[-1]["end"])
        else:
            base_start, base_end = None, None

        for o in overrides:
            s2, e2 = to_min(o["start"]), to_min(o["end"])
            if base_start is None or e2 > base_end or s2 < base_start:
                add_segment(result, o["start"], o["end"], override_status)

        return result

    base = with_gaps
    base = apply_overrides(base, ovp.get("open_windows", []), "available")
    base = apply_overrides(base, ovp.get("break_windows", []), "break")
    base = apply_overrides(base, ovp.get("block_windows", []), "blocked")

    # -------------------------------------------------------
    # 4️⃣ Merge adjacent same-status
    base.sort(key=lambda s: to_min(s["start"]))
    merged = []
    for seg in base:
        if merged and merged[-1]["status"] == seg["status"] and merged[-1]["end"] == seg["start"]:
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(seg)

    print(f"[DEBUG] Final Segments ({len(merged)}):")
    for s in merged:
        print(f"  {s['start']}–{s['end']}  [{s['status']}]")

    return {
        "setting": {
            "id": setting.id,
            "slot_minutes": setting.slot_minutes,
            "gap_minutes": setting.gap_minutes,
        },
        "segments": merged,
    }

@router.post("/slot-settings/update-status")
def update_slot_status(payload: UpdateSlotStatusPayload, db: Session = Depends(get_db)):
    """
    Update the status of a specific time range within a day's overrides.

    Rules:
      • 'blocked'  → add to block_windows
      • 'break'    → add to break_windows
      • 'available' → add to open_windows and remove overlaps from block/break
    """
    st, en = _parse_hhmm(payload.start), _parse_hhmm(payload.end)
    if en <= st:
        raise HTTPException(400, "end must be after start")

    setting = db.get(SlotSetting, payload.slot_setting_id)
    if not setting:
        raise HTTPException(404, "SlotSetting not found")

    ov = (
        db.query(SlotOverride)
          .filter(SlotOverride.slot_setting_id == payload.slot_setting_id,
                  SlotOverride.date == payload.date)
          .first()
    )

    merged_payload = dict(ov.payload or {}) if ov else {}

    def _clean_overlap(ranges: list[dict[str, str]]) -> list[dict[str, str]]:
        """Keep only those fully outside [st,en)."""
        out = []
        for r in ranges or []:
            rs, re = _parse_hhmm(r["start"]), _parse_hhmm(r["end"])
            if re <= st or rs >= en:
                out.append(r)
        return out

    # --------------------------------------------
    if payload.status in ("available", "working"):
        # remove overlaps from other categories
        merged_payload["block_windows"] = _clean_overlap(merged_payload.get("block_windows", []))
        merged_payload["break_windows"] = _clean_overlap(merged_payload.get("break_windows", []))

        # add/merge into open_windows
        merged_payload.setdefault("open_windows", [])
        merged_payload["open_windows"] = _clean_overlap(merged_payload["open_windows"])
        merged_payload["open_windows"].append({"start": payload.start, "end": payload.end})

    elif payload.status == "blocked":
        merged_payload.setdefault("block_windows", [])
        merged_payload["block_windows"] = _clean_overlap(merged_payload["block_windows"])
        merged_payload["block_windows"].append({"start": payload.start, "end": payload.end})

    elif payload.status == "break":
        merged_payload.setdefault("break_windows", [])
        merged_payload["break_windows"] = _clean_overlap(merged_payload["break_windows"])
        merged_payload["break_windows"].append({"start": payload.start, "end": payload.end})

    # --------------------------------------------
    # Ensure sorted, clean structure
    for key in ("open_windows", "block_windows", "break_windows"):
        lst = merged_payload.get(key)
        if lst:
            merged_payload[key] = sorted(lst, key=lambda x: x["start"])

    if ov:
        ov.payload = merged_payload
    else:
        ov = SlotOverride(
            slot_setting_id=payload.slot_setting_id,
            date=payload.date,
            payload=merged_payload,
        )
        db.add(ov)

    db.commit()
    db.refresh(ov)

    print(f"[DEBUG] Updated override {ov.id}: {merged_payload}")
    return {"ok": True, "id": ov.id, "payload": merged_payload}

@router.post("/slot-settings/split-window")
def split_window(payload: SplitWindowPayload, db: Session = Depends(get_db)):
    """
    Split an existing or virtual segment [start, end) into two parts at split_time.
    Uses the same logic as `/slots/preview` to understand the current day's segments,
    so even computed gaps can be split safely.
    """
    print("🟦 [SPLIT] Incoming payload:", payload.dict())

    st, en, mid = map(_parse_hhmm, [payload.start, payload.end, payload.split_time])
    if not (st < mid < en):
        raise HTTPException(400, "split_time must lie within the window")

    # Helper: choose correct override group
    def group_key_for(status: str) -> str:
        if status == "blocked":
            return "block_windows"
        if status == "break":
            return "break_windows"
        return "open_windows"

    # Helper converters (inline to avoid NameError)
    def to_min(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    def to_hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    # Step 1️⃣: Resolve slot setting and overrides
    setting = db.get(SlotSetting, payload.slot_setting_id)
    if not setting:
        raise HTTPException(404, "SlotSetting not found")

    day = _parse_date_or_400(payload.date)
    ovp = _load_override_payload(db, setting.id, day)
    working_windows = _compute_open_windows(setting, ovp, day)
    break_windows = ovp.get("break_windows", [])
    block_windows = ovp.get("block_windows", [])

    # Step 2️⃣: Rebuild all segments exactly like /slots/preview
    segments = []
    for win in working_windows:
        w_start = to_min(win["start"])
        w_end = to_min(win["end"])
        cur = w_start

        while cur < w_end:
            slot_start = cur
            slot_end = min(cur + setting.slot_minutes, w_end)
            overlaps = []
            for b in break_windows + block_windows:
                bs, be = to_min(b["start"]), to_min(b["end"])
                if bs < slot_end and be > slot_start:
                    overlaps.append(
                        (bs, be, "break" if b in break_windows else "blocked")
                    )
            if not overlaps:
                segments.append(
                    {"start": to_hhmm(slot_start), "end": to_hhmm(slot_end), "status": "available"}
                )
            else:
                slices = [(slot_start, slot_end, "available")]
                for bs, be, st in overlaps:
                    new_slices = []
                    for s0, s1, prev in slices:
                        if be <= s0 or bs >= s1:
                            new_slices.append((s0, s1, prev))
                        else:
                            if bs > s0:
                                new_slices.append((s0, bs, prev))
                            new_slices.append((max(bs, s0), min(be, s1), st))
                            if be < s1:
                                new_slices.append((be, s1, prev))
                    slices = new_slices
                for s0, s1, st in slices:
                    segments.append({"start": to_hhmm(s0), "end": to_hhmm(s1), "status": st})
            if cur + setting.slot_minutes + setting.gap_minutes < w_end:
                gap_start = slot_end
                gap_end = gap_start + setting.gap_minutes
                segments.append({"start": to_hhmm(gap_start), "end": to_hhmm(gap_end), "status": "gap"})
                cur = gap_end
            else:
                cur = slot_end

    print(f"🧾 Generated {len(segments)} segments for {day}")

    # Step 3️⃣: Locate clicked segment
    match = next(
        (s for s in segments if s["start"] == payload.start and s["end"] == payload.end),
        None,
    )
    if not match:
        print(f"⚪ No exact match for {payload.start}-{payload.end}, treating as gap.")
        current_status = "gap"
    else:
        current_status = match["status"]
        print(f"✅ Found clicked segment: {match}")

    # Step 4️⃣: Load or create override record
    ov = (
        db.query(SlotOverride)
        .filter(
            SlotOverride.slot_setting_id == setting.id,
            SlotOverride.date == day,
        )
        .first()
    )
    if not ov:
        ov = SlotOverride(
            slot_setting_id=setting.id,
            date=day,
            payload={"open_windows": [], "block_windows": [], "break_windows": []},
        )
        db.add(ov)
        db.flush()

    data = ov.payload or {}
    data.setdefault("open_windows", [])
    data.setdefault("block_windows", [])
    data.setdefault("break_windows", [])

    # Step 5️⃣: Perform the split
    left_group = group_key_for(payload.left_status or "available")
    right_group = group_key_for(payload.right_status or "available")

    if current_status == "gap":
        print("🟡 Splitting gap → new entries only")
        data[left_group].append({"start": payload.start, "end": payload.split_time})
        data[right_group].append({"start": payload.split_time, "end": payload.end})
    else:
        group = group_key_for(current_status)
        segs = data[group]
        match = next((s for s in segs if s["start"] == payload.start and s["end"] == payload.end), None)
        if match:
            segs.remove(match)
        data[left_group].append({"start": payload.start, "end": payload.split_time})
        data[right_group].append({"start": payload.split_time, "end": payload.end})

    # Step 6️⃣: Sort and persist
    for key in ("open_windows", "block_windows", "break_windows"):
        data[key] = sorted(data.get(key, []), key=lambda x: x["start"])

    ov.payload = dict(data)
    db.commit()

    print("💾 Split operation complete:", data)
    return {"ok": True, "payload": data}

@router.post("/slot-settings/merge-window")
def merge_window(payload: MergeWindowPayload, db: Session = Depends(get_db)):
    """
    Expand the clicked segment either backward or forward up to merge_time.
    Remove all overlapping segments (any status).
    """
    print(f"🟦 [MERGE] Incoming payload: {payload.model_dump()}")

    # Parse times
    st, en, merge_t = map(_parse_hhmm, [payload.start, payload.end, payload.merge_time])
    start_new = _format_hhmm(min(st, merge_t))
    end_new = _format_hhmm(max(en, merge_t))
    print(f"🔄 Merging range → {start_new} → {end_new}")

    # Load or create SlotOverride
    ov = (
        db.query(SlotOverride)
        .filter(
            SlotOverride.slot_setting_id == payload.slot_setting_id,
            SlotOverride.date == payload.date,
        )
        .first()
    )
    if not ov:
        ov = SlotOverride(
            slot_setting_id=payload.slot_setting_id,
            date=payload.date,
            payload={"open_windows": [], "block_windows": [], "break_windows": []},
        )
        db.add(ov)
        db.flush()

    data = ov.payload or {"open_windows": [], "block_windows": [], "break_windows": []}

    # Helper: map status → key
    def key_for(status: str) -> str:
        if status == "blocked":
            return "block_windows"
        if status == "break":
            return "break_windows"
        return "open_windows"

    # Remove all overlapping segments (any group)
    def overlaps(a, b):
        return not (a["end"] <= b["start"] or a["start"] >= b["end"])

    merged_range = {"start": start_new, "end": end_new}
    for key in list(data.keys()):
        before = len(data[key])
        data[key] = [seg for seg in data[key] if not overlaps(seg, merged_range)]
        removed = before - len(data[key])
        if removed:
            print(f"🗑 Removed {removed} from {key}")

    # Add the merged segment
    target_key = key_for(payload.status)
    data[target_key].append(merged_range)
    data[target_key] = sorted(data[target_key], key=lambda x: x["start"])

    ov.payload = data
    db.commit()

    print(f"✅ Merged as {payload.status}: {start_new}–{end_new}")
    return {"ok": True, "payload": data}

@router.delete("/slot-settings/revert/{slot_setting_id}/{date}")
def revert_override(slot_setting_id: int, date: str, db: Session = Depends(get_db)):
    """
    Delete SlotOverride for given slot_setting_id and date.
    """
    count = (
        db.query(SlotOverride)
        .filter(SlotOverride.slot_setting_id == slot_setting_id, SlotOverride.date == date)
        .delete()
    )
    db.commit()
    return {"ok": True, "deleted": count}

@router.post("/slot-settings/extend-window")
def extend_window(payload: dict, db: Session = Depends(get_db)):
    """
    Extend or shrink a segment by adjusting its boundary.
    payload:
      slot_setting_id, date,
      start, end,           # original segment
      direction: 'start' | 'end',
      new_time: 'HH:MM'
    """
    ov = (
        db.query(SlotOverride)
        .filter(
            SlotOverride.slot_setting_id == payload["slot_setting_id"],
            SlotOverride.date == payload["date"],
        )
        .first()
    )
    if not ov or not ov.payload:
        raise HTTPException(404, "No override found")

    data = ov.payload
    all_keys = ["open_windows", "block_windows", "break_windows"]
    # find which group contains this segment
    found_key, found_seg = None, None
    for k in all_keys:
        for s in data.get(k, []):
            if s["start"] == payload["start"] and s["end"] == payload["end"]:
                found_key, found_seg = k, s
                break
        if found_seg:
            break
    if not found_seg:
        raise HTTPException(404, "Segment not found")

    new_time = _parse_hhmm(payload["new_time"])
    st, en = map(_parse_hhmm, [payload["start"], payload["end"]])
    if payload["direction"] == "end":
        if new_time <= st:
            raise HTTPException(400, "End cannot precede start")
        found_seg["end"] = payload["new_time"]
    elif payload["direction"] == "start":
        if new_time >= en:
            raise HTTPException(400, "Start cannot exceed end")
        found_seg["start"] = payload["new_time"]

    # ✅ Adjust adjacent window (if any)
    for k in all_keys:
        for s in data.get(k, []):
            if k != found_key:
                # adjust overlapping boundary
                if s["start"] == payload["end"]:
                    s["start"] = payload["new_time"]
                elif s["end"] == payload["start"]:
                    s["end"] = payload["new_time"]

    for k in all_keys:
        data[k] = sorted(data[k], key=lambda x: x["start"])

    ov.payload = dict(data)
    db.commit()
    return {"ok": True, "payload": data}

@router.post("/slot-settings/extend-window")
def extend_window(payload: dict, db: Session = Depends(get_db)):
    """
    Extend or shrink a segment by adjusting its boundary.
    payload:
      slot_setting_id, date,
      start, end,           # original segment
      direction: 'start' | 'end',
      new_time: 'HH:MM'
    """
    ov = (
        db.query(SlotOverride)
        .filter(
            SlotOverride.slot_setting_id == payload["slot_setting_id"],
            SlotOverride.date == payload["date"],
        )
        .first()
    )
    if not ov or not ov.payload:
        raise HTTPException(404, "No override found")

    data = ov.payload
    all_keys = ["open_windows", "block_windows", "break_windows"]
    # find which group contains this segment
    found_key, found_seg = None, None
    for k in all_keys:
        for s in data.get(k, []):
            if s["start"] == payload["start"] and s["end"] == payload["end"]:
                found_key, found_seg = k, s
                break
        if found_seg:
            break
    if not found_seg:
        raise HTTPException(404, "Segment not found")

    new_time = _parse_hhmm(payload["new_time"])
    st, en = map(_parse_hhmm, [payload["start"], payload["end"]])
    if payload["direction"] == "end":
        if new_time <= st:
            raise HTTPException(400, "End cannot precede start")
        found_seg["end"] = payload["new_time"]
    elif payload["direction"] == "start":
        if new_time >= en:
            raise HTTPException(400, "Start cannot exceed end")
        found_seg["start"] = payload["new_time"]

    # ✅ Adjust adjacent window (if any)
    for k in all_keys:
        for s in data.get(k, []):
            if k != found_key:
                # adjust overlapping boundary
                if s["start"] == payload["end"]:
                    s["start"] = payload["new_time"]
                elif s["end"] == payload["start"]:
                    s["end"] = payload["new_time"]

    for k in all_keys:
        data[k] = sorted(data[k], key=lambda x: x["start"])

    ov.payload = dict(data)
    db.commit()
    return {"ok": True, "payload": data}

@router.get("/slot-settings/{setting_id}/export", tags=["slot-settings"])
def export_slot_setting(
    setting_id: int,
    include_overrides: bool = Query(False, description="Include all overrides for this setting"),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """Return the exact JSON saved for a specific SlotSetting id (incl. week_rules & blackout_dates)."""
    obj = db.get(SlotSetting, setting_id)
    if not obj:
        raise HTTPException(404, "SlotSetting not found")
    # ownership check
    if int(user["id"]) != obj.user_id:
        raise HTTPException(403, "Not your slot setting")

    out = {
        "id": obj.id,
        "user_id": obj.user_id,
        "location_id": obj.location_id,
        "consultation_type": obj.consultation_type,
        "slot_minutes": obj.slot_minutes,
        "gap_minutes": obj.gap_minutes,
        "per_slot_capacity": obj.per_slot_capacity,
        "lead_time_minutes": obj.lead_time_minutes,
        "booking_window_days": obj.booking_window_days,
        "visible_to_parents": obj.visible_to_parents,
        "effective_from": obj.effective_from.isoformat() if obj.effective_from else None,
        "effective_to": obj.effective_to.isoformat() if obj.effective_to else None,
        # 👇 exact JSON as persisted (multiple breaks preserved)
        "week_rules": obj.week_rules or {},
        "blackout_dates": obj.blackout_dates or [],
    }

    if include_overrides:
        ovs = (
            db.query(SlotOverride)
              .filter(SlotOverride.slot_setting_id == setting_id)
              .order_by(SlotOverride.date.asc())
              .all()
        )
        out["overrides"] = [
            {"date": o.date.isoformat(), "payload": o.payload or {}}
            for o in ovs
        ]

    return out


@router.get("/slot-settings/{setting_id}/overrides", tags=["slot-settings"])
def list_overrides_for_setting(
    setting_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """List all overrides (date + payload) for a SlotSetting id."""
    obj = db.get(SlotSetting, setting_id)
    if not obj:
        raise HTTPException(404, "SlotSetting not found")
    if int(user["id"]) != obj.user_id:
        raise HTTPException(403, "Not your slot setting")

    ovs = (
        db.query(SlotOverride)
          .filter(SlotOverride.slot_setting_id == setting_id)
          .order_by(SlotOverride.date.asc())
          .all()
    )
    return [{"date": o.date.isoformat(), "payload": o.payload or {}} for o in ovs]


@router.get("/slot-settings/{setting_id}/overrides/{date}", tags=["slot-settings"])
def get_override_for_date(
    setting_id: int,
    date: str,  # YYYY-MM-DD
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """Get a single day's override payload for this setting id."""
    obj = db.get(SlotSetting, setting_id)
    if not obj:
        raise HTTPException(404, "SlotSetting not found")
    if int(user["id"]) != obj.user_id:
        raise HTTPException(403, "Not your slot setting")

    day = _parse_date_or_400(date)
    ov = (
        db.query(SlotOverride)
          .filter(SlotOverride.slot_setting_id == setting_id, SlotOverride.date == day)
          .first()
    )
    return {"date": day.isoformat(), "payload": (ov.payload if ov else {}) or {}}
