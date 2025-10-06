# app/routers/slot_settings.py
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Literal, Dict, Any
from app.dependencies import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, JSON, Boolean,
    UniqueConstraint, Index, or_
)
from sqlalchemy.orm import Session
from app.api.models import Base

router = APIRouter(prefix="/api/v1", tags=["slot-settings"])

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
# SQLAlchemy models (user_id + vet_locations FK)
# =============================================================================

class SlotSetting(Base):
    __tablename__ = "slot_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Context (required)
    user_id = Column(Integer, nullable=False, index=True)             # FK users(id)
    location_id = Column(Integer, nullable=True, index=True)          # FK vet_locations(id); required for in_person
    consultation_type = Column(String, nullable=False)                # 'in_person' | 'video'

    # Core knobs
    slot_minutes = Column(Integer, nullable=False, default=15)        # consult length
    gap_minutes = Column(Integer, nullable=False, default=0)          # buffer between slots
    per_slot_capacity = Column(Integer, nullable=False, default=1)
    lead_time_minutes = Column(Integer, nullable=False, default=0)    # rolling buffer (parent view, same day)
    booking_window_days = Column(Integer, nullable=False, default=30) # rolling horizon
    visible_to_parents = Column(Boolean, nullable=False, default=True)

    # Template & exceptions
    week_rules = Column(JSON, nullable=False, default={})             # validated via Pydantic on create/update
    blackout_dates = Column(JSON, nullable=False, default=[])

    # Optional versioning of rules
    effective_from = Column(Date, nullable=True)
    effective_to   = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "location_id", "consultation_type", name="uq_slot_settings_ctx"),
        Index("ix_slot_settings_effective", "effective_from", "effective_to"),
    )


class SlotOverride(Base):
    __tablename__ = "slot_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot_setting_id = Column(Integer, ForeignKey("slot_settings.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    payload = Column(JSON, nullable=False, default={})                # validated on input

    __table_args__ = (
        UniqueConstraint("slot_setting_id", "date", name="uq_slot_overrides_day"),
    )


# =============================================================================
# Request/Response Schemas
# =============================================================================

class SlotSettingCreate(BaseModel):
    """Create/update payload for slot settings (template + knobs)."""
    user_id: int
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


class CapacityOverrideRange(TimeRange):
    """Temporarily change capacity inside a subrange."""
    capacity: int = Field(..., ge=1, le=10)


class OverridePayload(BaseModel):
    """Per-day overrides (do not change the weekly template)."""
    open_windows: Optional[List[TimeRange]] = None          # replaces the day windows
    block_windows: Optional[List[TimeRange]] = None         # makes subranges unavailable
    extra_slots: Optional[List[ExtraSlotRange]] = None      # add ad-hoc windows
    capacity_overrides: Optional[List[CapacityOverrideRange]] = None  # temp capacity changes


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


class Slot(BaseModel):
    """A computed time slice with its availability."""
    start: str
    end: str
    capacity: int
    booked: int = 0
    status: Literal["available", "full", "blocked"] = "available"


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

@router.post("/slot-settings", response_model=SlotSettingRead)
def create_slot_setting(payload: SlotSettingCreate, db: Session = Depends(get_db)):
    """
    Create slot settings (template + knobs) for a (user_id, location_id, consultation_type) context.

    Rules:
      - For 'in_person', location_id is required.
      - Uniqueness per (user_id, location_id, consultation_type).
      - Effective date ranges must not overlap for the same context.
    """
    q = db.query(SlotSetting).filter(
        SlotSetting.user_id == payload.user_id,
        SlotSetting.consultation_type == payload.consultation_type,
        SlotSetting.location_id == payload.location_id
    )
    # Disallow overlapping effective ranges for the same context
    rows = q.all()
    for r in rows:
        if _ranges_overlap(payload.effective_from, payload.effective_to, r.effective_from, r.effective_to):
            raise HTTPException(status_code=409, detail="Overlapping effective date ranges for the same context")
    if rows:
        raise HTTPException(status_code=409, detail="Slot settings already exist for this user/location/type")

    obj = SlotSetting(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
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


@router.put("/slot-settings/{setting_id}", response_model=SlotSettingRead)
def update_slot_setting(setting_id: int, payload: SlotSettingCreate, db: Session = Depends(get_db)):
    """
    Update a SlotSetting. Maintains uniqueness and prevents overlapping effective ranges
    for the same (user, location, type) context.
    """
    obj = db.get(SlotSetting, setting_id)
    if not obj: raise HTTPException(status_code=404, detail="Not found")

    q = db.query(SlotSetting).filter(
        SlotSetting.id != setting_id,
        SlotSetting.user_id == payload.user_id,
        SlotSetting.consultation_type == payload.consultation_type,
        SlotSetting.location_id == payload.location_id
    )
    rows = q.all()
    for r in rows:
        if _ranges_overlap(payload.effective_from, payload.effective_to, r.effective_from, r.effective_to):
            raise HTTPException(status_code=409, detail="Overlapping effective date ranges for the same context")
    if rows:
        raise HTTPException(status_code=409, detail="Duplicate user/location/type exists")

    for k, v in payload.model_dump().items():
        setattr(obj, k, v)
    db.commit(); db.refresh(obj)
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

@router.get("/slots", response_model=List[Slot])
def get_slots_for_day(
    user_id: int = Query(..., description="Vet's user id"),
    date_str: str = Query(..., description="YYYY-MM-DD"),
    location_id: int = Query(..., description="vet_locations.id (required for in_person; recommended for video)"),
    consultation_type: Literal["video", "in_person"] = Query(...),
    public: bool = False,
    db: Session = Depends(get_db)
):
    """
    Return the computed appointment slots for a (user/location/type) on a given date.

    Definition:
        The algorithm composes the slot-generation pipeline from clear steps:
        1) parse date
        2) resolve effective slot settings for (user, location, type)
        3) apply visibility rules (blackouts, parent horizon, etc.)
        4) load per-date overrides (if any)
        5) choose the day's open windows (override > weekly rules)
        6) generate baseline slots using slot_minutes + gap_minutes
        7) add extra slots (ad-hoc windows)
        8) apply capacity overrides + booked counts, hide non-available for parent view
        9) sort and return

    Example:
        GET /api/v1/slots?user_id=17&location_id=101&consultation_type=in_person&date_str=2025-10-03&public=true
    """
    day = _parse_date_or_400(date_str)

    # 1) Resolve the single setting row for (user, location, type) that is effective on 'day'
    setting = _resolve_setting_or_404(db, user_id, location_id, consultation_type, day)

    # 2) Quick visibility checks (blackout, parent visibility flag, booking window)
    if not _is_visible_today(setting, day, public):
        return []

    # 3) Load override payload for that (setting, day)
    ovp = _load_override_payload(db, setting.id, day)

    # 4) Decide the open windows for the day (override open_windows > weekly rules)
    base_windows = _compute_open_windows(setting, ovp, day)
    if not base_windows:
        return []

    # 5) Generate baseline slots from windows
    slots = _generate_baseline_slots(
        base_windows=base_windows,
        slot_minutes=setting.slot_minutes,
        gap_minutes=setting.gap_minutes,
        per_slot_capacity=setting.per_slot_capacity,
        block_windows=ovp.get("block_windows", []),
        breaks_in_windows=True,
        lead_cutoff=_lead_cutoff_for_public(public, setting, day),
    )

    # 6) Add explicit extra slots (ad-hoc windows, optional custom size/capacity)
    slots.extend(_generate_extra_slots(
        extra_slots=ovp.get("extra_slots", []),
        default_slot_minutes=setting.slot_minutes,
        gap_minutes=setting.gap_minutes,
        default_capacity=setting.per_slot_capacity,
        block_windows=ovp.get("block_windows", []),
    ))

    # 7) Apply capacity overrides, mark booked/full/blocked, then filter for parent view
    slots = _mark_status_and_filter(
        slots=slots,
        capacity_overrides=ovp.get("capacity_overrides", []),
        default_capacity=setting.per_slot_capacity,
        booked_map={},  # TODO: wire Appointment counts here
        public=public,
    )

    # 8) Sort and return
    slots.sort(key=lambda s: s.start)
    return slots


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
    Compute the 'lead time' cutoff for parent view on same day; else None.
    If `lead_time_minutes=120` and now=09:05, cutoff=11:05 and earlier-starting slots are hidden.
    """
    if not public or not setting.lead_time_minutes or day != date.today():
        return None
    return (datetime.utcnow() + timedelta(minutes=setting.lead_time_minutes)).time()


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
) -> List[Slot]:
    """Add ad-hoc windows; may have custom slot_minutes/capacity. Honor block windows."""
    out: List[Slot] = []
    for ex in extra_slots or []:
        st, en = _parse_hhmm(ex["start"]), _parse_hhmm(ex["end"])
        step = int(ex.get("slot_minutes", default_slot_minutes))
        cap = int(ex.get("capacity", default_capacity))
        for t0, t1 in _time_walk(st, en, step, gap_minutes):
            if any(_overlaps(bw, t0, t1) for bw in (block_windows or [])):
                out.append(Slot(start=_format_hhmm(t0), end=_format_hhmm(t1), capacity=0, status="blocked"))
            else:
                out.append(Slot(start=_format_hhmm(t0), end=_format_hhmm(t1), capacity=cap))
    return out


def _mark_status_and_filter(
    slots: List[Slot],
    capacity_overrides: List[Dict[str, Any]],
    default_capacity: int,
    booked_map: Dict[tuple, int],
    public: bool,
) -> List[Slot]:
    """
    Apply capacity overrides and booked counts, compute final status, and filter for parent view.
    - Capacity override applies when a slot is wholly within the override range.
    - Blocked capacity (0) stays blocked; booked >= capacity -> full.
    - Parent view returns only 'available'; vet view returns all.
    """
    def capacity_for(t0: str, t1: str) -> int:
        t0t, t1t = _parse_hhmm(t0), _parse_hhmm(t1)
        for cw in (capacity_overrides or []):
            if _within(cw, t0t, t1t):
                return int(cw.get("capacity", default_capacity))
        return default_capacity

    for s in slots:
        if s.status != "blocked":
            s.capacity = capacity_for(s.start, s.end)

        key = (s.start, s.end)
        s.booked = booked_map.get(key, 0)

        if s.capacity == 0:
            s.status = "blocked"
        elif s.booked >= s.capacity:
            s.status = "full"
        else:
            s.status = "available"

    return [s for s in slots if (s.status == "available")] if public else slots
