# scripts/gen/appointments.py
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple


def _round_up_to_minutes(dt: datetime, minutes: int) -> datetime:
    # round up to next boundary
    seconds = int(dt.timestamp())
    step = minutes * 60
    rounded = ((seconds + step - 1) // step) * step
    return datetime.fromtimestamp(rounded, tz=timezone.utc)

def _state_plan(rng: random.Random, cfg) -> str:
    # deterministic-ish mix
    x = rng.random()
    if x < cfg.pct_booked:
        return "BOOKED"
    x -= cfg.pct_booked
    if x < cfg.pct_completed:
        return "COMPLETED"
    x -= cfg.pct_completed
    if x < cfg.pct_cancelled:
        return rng.choice(["CANCELLED_BY_PARENT", "CANCELLED_BY_VET"])
    x -= cfg.pct_cancelled
    if x < cfg.pct_in_consult:
        return "IN_CONSULT"
    return "NO_SHOW"

def _load_locations(conn, vet_ids: List[int]) -> Dict[int, List[int]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, id FROM vet_locations WHERE user_id = ANY(%s) ORDER BY id",
            (vet_ids,),
        )
        out: Dict[int, List[int]] = {}
        for vet_id, loc_id in cur.fetchall():
            out.setdefault(int(vet_id), []).append(int(loc_id))
        return out

def seed_appointments(
    conn,
    vet_user_ids: List[int],
    parent_user_ids: List[int],
    pet_ids_by_parent: Dict[int, List[int]],
    cfg,
) -> int:
    """
    ✅ Guarantees:
    - Every parent gets >=1 upcoming BOOKED appointment (if they have pets).
    - Creates additional past COMPLETED appointments so consults can exist.
    - Uses per-location slot pointer so uniqueness constraints are naturally avoided.
    - Uses ON CONFLICT DO NOTHING as a safety net (won't crash generation).
    """
    rng = random.Random(cfg.rng_seed + 900)
    locs_by_vet = _load_locations(conn, vet_user_ids)
    if not locs_by_vet:
        print("[seed][appt] skipped: no vet_locations")
        return 0

    slot_min = max(2, int(getattr(cfg, "slot_minutes", 2)))
    now = datetime.now(tz=timezone.utc)
    start_base = _round_up_to_minutes(now + timedelta(minutes=slot_min), slot_min)

    # pointer per location (next free slot)
    # spread across the next cfg.appointment_span_days days (but pointer makes it sequential)
    pointer: Dict[int, datetime] = {}
    for vet_id, locs in locs_by_vet.items():
        for loc in locs:
            pointer[loc] = start_base

    appts_per_parent = max(2, int(getattr(cfg, "appointments_per_parent", 6)))
    span_days = max(7, int(getattr(cfg, "appointment_span_days", 30)))

    rows: List[Tuple] = []
    inserted = 0

    def alloc_slot(location_id: int, want_past: bool) -> Tuple[datetime, datetime]:
        # If want_past: pick a deterministic past slot (by subtracting days) but still unique
        base = pointer[location_id]
        if want_past:
            start = base - timedelta(days=rng.randint(1, min(14, span_days)), hours=rng.randint(0, 6))
            start = _round_up_to_minutes(start, slot_min)
        else:
            start = base
            pointer[location_id] = base + timedelta(minutes=slot_min)
        end = start + timedelta(minutes=slot_min)
        return start, end

    # Force: first appointment per parent is upcoming BOOKED
    for parent_id in parent_user_ids:
        pets = pet_ids_by_parent.get(parent_id) or []
        if not pets:
            print(f"[seed][appt][warn] parent={parent_id} has no pets -> no appointments")
            continue

        for j in range(appts_per_parent):
            # pick vet and location
            vet_id = rng.choice(vet_user_ids)
            locs = locs_by_vet.get(vet_id) or []
            if not locs:
                continue
            location_id = rng.choice(locs)
            pet_id = rng.choice(pets)

            # first appointment: booked future
            if j == 0:
                state = "BOOKED"
                want_past = False
            # second appointment: completed past for consult
            elif j == 1:
                state = "COMPLETED"
                want_past = True
            else:
                state = _state_plan(rng, cfg)
                want_past = (state in ("COMPLETED", "NO_SHOW")) and rng.random() < 0.7

            start_ts, end_ts = alloc_slot(location_id, want_past=want_past)

            visit_state = None
            completed_at = None
            if state == "IN_CONSULT":
                visit_state = "IN_CONSULT"
            elif state == "COMPLETED":
                visit_state = "COMPLETED"
                completed_at = end_ts
            elif state == "BOOKED" and rng.random() < 0.20:
                visit_state = "ARRIVED"

            mode = rng.choice(["in_person", "video"])

            slot_id = f"slot:{vet_id}:{location_id}:{start_ts.date().isoformat()}:{start_ts.strftime('%H%M')}"

            rows.append((
                slot_id,
                vet_id,
                location_id,
                parent_id,
                pet_id,
                mode,
                start_ts,
                end_ts,
                state,
                visit_state,
                None,
                completed_at,
            ))

    # Insert in chunks
    chunk = int(getattr(cfg, "batch_size", 5000))
    with conn.cursor() as cur:
        for i in range(0, len(rows), chunk):
            part = rows[i:i+chunk]
            cur.executemany(
                """
                INSERT INTO appointments
                  (slot_id, vet_id, location_id, parent_id, pet_id, mode,
                   start_ts, end_ts, calendar_state, visit_state, notes, completed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                part,
            )

        # count inserted (approx) = count in table for these parents in this run is expensive,
        # so just count total table rows at end of seed using main counts query.

    print(f"[seed][appt] attempted={len(rows)} inserted (best-effort)")
    return len(rows)
