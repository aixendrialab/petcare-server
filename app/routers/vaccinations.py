from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.dependencies import get_db
from app.routers.security import require_user

from datetime import date, timedelta
from typing import Optional, List, Dict, Any, Tuple

from app.api.models.vaccinations import (
    VaccinesDueResponse, VaccineDueItem,
    VaccinesSummaryResponse, PetVaccineSummary,
    PetPlanResponse, PetInfo, VaccinePlanInfo, VaccinePlanItem, VaccinationRecordOut,
    RecommendedPlanResponse, RecommendedPlanItem,
    AcceptPlanResponse,
    CreateVaccinationRecordIn, CreateVaccinationRecordOut,
    CreateVaccinationIntentIn, CreateVaccinationIntentOut,
    VetVaccinationRequestsResponse, VetVaccinationRequestItem,
    VetAppointmentVaccinationContext,
    VetConfirmPlanIn, VetConfirmPlanOut,
    CreateVetVaccinationRecordIn, CreateVetVaccinationRecordOut,
)

router = APIRouter(
    dependencies=[Depends(require_user)],
)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _infer_species_from_pet(breed: Optional[str]) -> str:
    """
    Back-compat heuristic. Prefer pets.species if you have it (you do).
    """
    if not breed:
        return "dog"
    b = breed.lower()
    if "cat" in b or "persian" in b or "siamese" in b or "ragdoll" in b:
        return "cat"
    return "dog"


def _get_pet(db: Session, pet_id: int) -> Dict[str, Any]:
    pet = db.execute(
        text("""
            SELECT id, user_id, name, breed, dob, species
            FROM pets
            WHERE id=:pid
        """),
        {"pid": pet_id},
    ).mappings().first()
    if not pet:
        raise HTTPException(404, "Pet not found")
    return dict(pet)


def _resolve_vaccine_id(
    db: Session,
    *,
    vaccine_id: Optional[int],
    vaccine_code: Optional[str],
    vaccine_species: Optional[str],
) -> Dict[str, Any]:
    """
    Returns vaccine row: {id, code, species, name, vaccine_type}
    Accepts either:
      - vaccine_id, OR
      - (vaccine_code + vaccine_species)
    """
    if vaccine_id:
        row = db.execute(
            text("""
                SELECT id, code, species, name, vaccine_type
                FROM vaccine_catalog
                WHERE id=:id AND is_active=true
            """),
            {"id": vaccine_id},
        ).mappings().first()
        if not row:
            raise HTTPException(400, "Invalid vaccine_id")
        return dict(row)

    if vaccine_code and vaccine_species:
        row = db.execute(
            text("""
                SELECT id, code, species, name, vaccine_type
                FROM vaccine_catalog
                WHERE code=:c AND species=:s AND is_active=true
            """),
            {"c": vaccine_code, "s": vaccine_species},
        ).mappings().first()
        if not row:
            raise HTTPException(400, "Invalid vaccine_code/vaccine_species")
        return dict(row)

    raise HTTPException(400, "vaccine_id OR (vaccine_code + vaccine_species) required")


def _get_or_create_plan(db: Session, pet_id: int, species: Optional[str] = None) -> Optional[int]:
    """
    Ensures pet_vaccine_plan + items exist for the pet (SUGGESTED).
    If pet has no DOB, returns None (cannot generate schedule).
    """
    existing = db.execute(
        text("SELECT id FROM pet_vaccine_plan WHERE pet_id=:pid"),
        {"pid": pet_id},
    ).mappings().first()
    if existing:
        return int(existing["id"])

    pet = _get_pet(db, pet_id)
    if not pet.get("dob"):
        return None

    species_eff = species or pet.get("species") or _infer_species_from_pet(pet.get("breed"))
    dob: date = pet["dob"]
    today = date.today()

    plan_row = db.execute(
        text("""
            INSERT INTO pet_vaccine_plan (pet_id, status, generated_at)
            VALUES (:pid, 'SUGGESTED', now())
            RETURNING id
        """),
        {"pid": pet_id},
    ).mappings().first()
    plan_id = int(plan_row["id"])

    # IMPORTANT: vaccine_rule now references vaccine_id (numeric)
    rules = db.execute(
        text("""
            SELECT
              r.id,
              r.vaccine_id,
              r.start_age_weeks,
              r.dose_count,
              r.dose_interval_days,
              r.booster_interval_days,
              c.code AS vaccine_code,
              c.species AS vaccine_species,
              c.name AS vaccine_name,
              c.vaccine_type
            FROM vaccine_rule r
            JOIN vaccine_catalog c ON c.id = r.vaccine_id
            WHERE r.species=:species
              AND r.is_active=true
              AND c.is_active=true
            ORDER BY c.vaccine_type, c.name
        """),
        {"species": species_eff},
    ).mappings().all()

    for r in rules:
        start_weeks = int(r["start_age_weeks"] or 0)
        dose_count = int(r["dose_count"] or 1)
        interval_days = int(r["dose_interval_days"] or 21)
        booster_days = r["booster_interval_days"]

        for dose_no in range(1, dose_count + 1):
            due_on = dob + timedelta(days=start_weeks * 7 + (dose_no - 1) * interval_days)
            st = "DUE" if due_on <= today else "UPCOMING"
            db.execute(
                text("""
                    INSERT INTO pet_vaccine_plan_item
                      (plan_id, vaccine_id, vaccine_code, vaccine_species, dose_no, due_on, status, overridden)
                    VALUES
                      (:plan_id, :vaccine_id, :code, :species, :dose_no, :due_on, :status, false)
                """),
                {
                    "plan_id": plan_id,
                    "vaccine_id": int(r["vaccine_id"]),
                    "code": r["vaccine_code"],
                    "species": r["vaccine_species"],
                    "dose_no": dose_no,
                    "due_on": due_on,
                    "status": st,
                },
            )

        if booster_days:
            last_due = dob + timedelta(days=start_weeks * 7 + (dose_count - 1) * interval_days)
            booster_due = last_due + timedelta(days=int(booster_days))
            st = "DUE" if booster_due <= today else "UPCOMING"
            db.execute(
                text("""
                    INSERT INTO pet_vaccine_plan_item
                      (plan_id, vaccine_id, vaccine_code, vaccine_species, dose_no, due_on, status, overridden)
                    VALUES
                      (:plan_id, :vaccine_id, :code, :species, 0, :due_on, :status, false)
                """),
                {
                    "plan_id": plan_id,
                    "vaccine_id": int(r["vaccine_id"]),
                    "code": r["vaccine_code"],
                    "species": r["vaccine_species"],
                    "due_on": booster_due,
                    "status": st,
                },
            )

    db.commit()
    return plan_id


def _load_plan_items(db: Session, plan_id: int) -> Dict[str, List[Dict[str, Any]]]:
    rows = db.execute(
        text("""
            SELECT
              i.id,
              i.vaccine_id,
              i.vaccine_code,
              i.vaccine_species,
              c.name AS vaccine_name,
              i.dose_no,
              i.due_on,
              i.status,
              i.overridden,
              i.override_reason,
              i.completed_on,
              i.completed_record_id
            FROM pet_vaccine_plan_item i
            JOIN vaccine_catalog c ON c.id = i.vaccine_id
            WHERE i.plan_id=:pid
            ORDER BY i.due_on ASC, c.name ASC, i.dose_no ASC
        """),
        {"pid": plan_id},
    ).mappings().all()

    today = date.today()
    due_now, upcoming, completed = [], [], []

    for r in rows:
        rr = dict(r)

        if rr["status"] == "COMPLETED" or rr.get("completed_on") is not None:
            rr["status"] = "COMPLETED"
            completed.append(rr)
            continue

        if rr["status"] in ("SKIPPED", "MISSED"):
            due_now.append(rr)
            continue

        if rr["due_on"] and rr["due_on"] <= today:
            rr["status"] = "DUE"
            due_now.append(rr)
        else:
            rr["status"] = "UPCOMING"
            upcoming.append(rr)

    return {"due_now": due_now, "upcoming": upcoming, "completed": completed}


def _load_records(db: Session, pet_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text("""
            SELECT
              r.id,
              r.pet_id,
              r.vaccine_id,
              r.vaccine_code,
              r.vaccine_species,
              c.name AS vaccine_name,
              COALESCE(r.vaccine_type, c.vaccine_type) AS vaccine_type,
              r.last_given,
              r.next_due,
              r.batch_no,
              r.manufacturer,
              r.notes,
              r.vet_id,
              r.location_id,
              r.created_at
            FROM vaccination_record r
            JOIN vaccine_catalog c ON c.id = r.vaccine_id
            WHERE r.pet_id=:pid
            ORDER BY r.last_given DESC NULLS LAST, r.created_at DESC
        """),
        {"pid": pet_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _complete_matching_plan_item(
    db: Session,
    *,
    pet_id: int,
    vaccine_id: int,
    last_given: date,
    record_id: int,
):
    plan = db.execute(
        text("SELECT id FROM pet_vaccine_plan WHERE pet_id=:pid"),
        {"pid": pet_id},
    ).mappings().first()
    if not plan:
        return

    plan_id = int(plan["id"])

    item = db.execute(
        text("""
            SELECT id, due_on
            FROM pet_vaccine_plan_item
            WHERE plan_id=:plan_id
              AND vaccine_id=:vid
              AND status NOT IN ('COMPLETED','SKIPPED')
              AND completed_on IS NULL
            ORDER BY ABS(EXTRACT(EPOCH FROM (due_on::timestamp - :given::timestamp))) ASC
            LIMIT 1
        """),
        {"plan_id": plan_id, "vid": vaccine_id, "given": last_given},
    ).mappings().first()

    if not item:
        return

    db.execute(
        text("""
            UPDATE pet_vaccine_plan_item
            SET status='COMPLETED',
                completed_on=:given,
                completed_record_id=:rid
            WHERE id=:iid
        """),
        {"iid": int(item["id"]), "given": last_given, "rid": record_id},
    )

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------

@router.get("/history/{pet_id}")
def get_vaccine_history(
    pet_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")

    rows = db.execute(
        text("""
            SELECT
              r.id,
              c.name AS vaccine_name,
              r.last_given,
              r.next_due
            FROM vaccination_record r
            JOIN vaccine_catalog c ON c.id = r.vaccine_id
            WHERE r.pet_id=:pid
            ORDER BY r.last_given DESC NULLS LAST, r.created_at DESC
        """),
        {"pid": pet_id},
    ).mappings().all()

    # keep this output shape if your UI expects it
    return [
        {
            "id": int(r["id"]),
            "name": r["vaccine_name"],
            "lastGiven": r["last_given"].isoformat() if r["last_given"] else None,
            "nextDue": r["next_due"].isoformat() if r["next_due"] else None,
        }
        for r in rows
    ]


# ---------------------------
# Parent endpoints
# ---------------------------

@router.get("/due", response_model=VaccinesDueResponse)
def get_due(
    mine: int = Query(1),
    limit: int = Query(3, ge=1, le=50),
    upcoming_days: int = Query(30, ge=0, le=365),  # ✅ include upcoming window
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])

    # Ensure plan exists for all my pets (helps home screen)
    if mine == 1:
        pet_ids = db.execute(
            text("SELECT id FROM pets WHERE user_id=:uid"),
            {"uid": user_id},
        ).scalars().all()
        for pid in pet_ids:
            _get_or_create_plan(db, int(pid))

    rows = db.execute(
    text("""
        SELECT
          p.id AS pet_id,
          p.name AS pet_name,
          i.id AS plan_item_id,

          i.vaccine_id AS vaccine_id,     -- ✅ ADD THIS
          c.code AS vaccine_code,
          c.species AS vaccine_species,
          c.name AS vaccine_name,

          i.dose_no,
          i.due_on,
          CASE
            WHEN i.completed_on IS NOT NULL THEN 'COMPLETED'
            WHEN i.status IN ('SKIPPED','MISSED') THEN i.status
            WHEN i.due_on <= CURRENT_DATE THEN 'DUE'
            ELSE 'UPCOMING'
          END AS status
        FROM pet_vaccine_plan_item i
        JOIN pet_vaccine_plan pl ON pl.id = i.plan_id
        JOIN pets p ON p.id = pl.pet_id
        JOIN vaccine_catalog c ON c.id = i.vaccine_id
        WHERE (:mine = 0 OR p.user_id = :uid)
          AND i.completed_on IS NULL
          AND i.status NOT IN ('COMPLETED','SKIPPED')
          AND i.due_on <= (CURRENT_DATE + (:upcoming_days || ' days')::interval)
        ORDER BY
          CASE WHEN i.due_on <= CURRENT_DATE THEN 0 ELSE 1 END,
          i.due_on ASC
        LIMIT :limit
    """),
    {"mine": mine, "uid": user_id, "limit": limit, "upcoming_days": upcoming_days},
).mappings().all()


    return {"items": [VaccineDueItem(**dict(r)) for r in rows]}


@router.get("/summary", response_model=VaccinesSummaryResponse)
def get_summary(
    mine: int = Query(1),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    if mine != 1:
        raise HTTPException(400, "Only mine=1 supported for now")

    pets = db.execute(
        text("SELECT id, name, breed, dob, species FROM pets WHERE user_id=:uid ORDER BY id"),
        {"uid": user_id},
    ).mappings().all()

    out: List[PetVaccineSummary] = []
    for p in pets:
        pid = int(p["id"])
        _get_or_create_plan(db, pid)

        plan = db.execute(
            text("SELECT id, status FROM pet_vaccine_plan WHERE pet_id=:pid"),
            {"pid": pid},
        ).mappings().first()

        counts = db.execute(
            text("""
        SELECT
          SUM(CASE WHEN i.completed_on IS NOT NULL THEN 1 ELSE 0 END) AS completed,
          SUM(CASE
                WHEN i.completed_on IS NULL
                 AND i.due_on <= CURRENT_DATE
                 AND i.status NOT IN ('SKIPPED')
              THEN 1 ELSE 0 END) AS due,
          SUM(CASE
                WHEN i.completed_on IS NULL
                 AND i.due_on > CURRENT_DATE
                 AND i.status NOT IN ('SKIPPED')
              THEN 1 ELSE 0 END) AS upcoming,
          SUM(CASE WHEN i.status='MISSED' THEN 1 ELSE 0 END) AS overdue
        FROM pet_vaccine_plan_item i
        JOIN pet_vaccine_plan pl ON pl.id=i.plan_id
        WHERE pl.pet_id=:pid
    """),
    {"pid": pid},
        ).mappings().first() or {}


        out.append(
            PetVaccineSummary(
                pet_id=pid,
                pet_name=p["name"],
                plan_status=plan["status"] if plan else None,
                overdue=int(counts.get("overdue") or 0),
                due=int(counts.get("due") or 0),
                upcoming=int(counts.get("upcoming") or 0),
                completed=int(counts.get("completed") or 0),
            )
        )

    return {"pets": out}


@router.get("/pets/{pet_id}/plan", response_model=PetPlanResponse)
def get_pet_plan(
    pet_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")

    plan_id = _get_or_create_plan(db, pet_id)
    plan_info = None
    items = {"due_now": [], "upcoming": [], "completed": []}

    if plan_id:
        pl = db.execute(
            text("""
                SELECT id, status, generated_at, confirmed_at, confirmed_by_vet_id
                FROM pet_vaccine_plan
                WHERE id=:id
            """),
            {"id": plan_id},
        ).mappings().first()
        plan_info = VaccinePlanInfo(**dict(pl))
        items = _load_plan_items(db, plan_id)

    records = _load_records(db, pet_id)

    return PetPlanResponse(
        pet=PetInfo(
            id=pet["id"],
            name=pet["name"],
            breed=pet.get("breed"),
            dob=pet.get("dob"),
            species=pet.get("species") or _infer_species_from_pet(pet.get("breed")),
        ),
        plan=plan_info,
        due_now=[VaccinePlanItem(**x) for x in items["due_now"]],
        upcoming=[VaccinePlanItem(**x) for x in items["upcoming"]],
        completed=[VaccinePlanItem(**x) for x in items["completed"]],
        records=[VaccinationRecordOut(**r) for r in records],
    )


@router.get("/pets/{pet_id}/recommended", response_model=RecommendedPlanResponse)
def get_recommended(
    pet_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")

    if not pet.get("dob"):
        return {"pet_id": pet_id, "items": []}

    species_eff = pet.get("species") or _infer_species_from_pet(pet.get("breed"))
    dob: date = pet["dob"]

    rules = db.execute(
        text("""
            SELECT
              r.vaccine_id,
              r.start_age_weeks,
              r.dose_count,
              r.dose_interval_days,
              r.booster_interval_days,
              c.code AS vaccine_code,
              c.species AS vaccine_species,
              c.name AS vaccine_name,
              c.vaccine_type
            FROM vaccine_rule r
            JOIN vaccine_catalog c ON c.id=r.vaccine_id
            WHERE r.species=:s AND r.is_active=true AND c.is_active=true
            ORDER BY c.vaccine_type, c.name
        """),
        {"s": species_eff},
    ).mappings().all()

    items: List[RecommendedPlanItem] = []
    for r in rules:
        start_weeks = int(r["start_age_weeks"] or 0)
        dose_count = int(r["dose_count"] or 1)
        interval_days = int(r["dose_interval_days"] or 21)
        booster_days = r["booster_interval_days"]

        for dose_no in range(1, dose_count + 1):
            due_on = dob + timedelta(days=start_weeks * 7 + (dose_no - 1) * interval_days)
            items.append(
                RecommendedPlanItem(
                    vaccine_id=int(r["vaccine_id"]),
                    vaccine_code=r["vaccine_code"],
                    vaccine_species=r["vaccine_species"],
                    vaccine_name=r["vaccine_name"],
                    dose_no=dose_no,
                    due_on=due_on,
                    vaccine_type=r["vaccine_type"],
                )
            )

        if booster_days:
            last_due = dob + timedelta(days=start_weeks * 7 + (dose_count - 1) * interval_days)
            booster_due = last_due + timedelta(days=int(booster_days))
            items.append(
                RecommendedPlanItem(
                    vaccine_id=int(r["vaccine_id"]),
                    vaccine_code=r["vaccine_code"],
                    vaccine_species=r["vaccine_species"],
                    vaccine_name=r["vaccine_name"],
                    dose_no=0,
                    due_on=booster_due,
                    vaccine_type=r["vaccine_type"],
                )
            )

    items.sort(key=lambda x: (x.due_on, x.vaccine_name, x.dose_no))
    return {"pet_id": pet_id, "items": items}


@router.post("/pets/{pet_id}/plan/accept", response_model=AcceptPlanResponse)
def accept_plan(
    pet_id: int,
    species: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")

    plan_id = _get_or_create_plan(db, pet_id, species=species)
    if not plan_id:
        raise HTTPException(400, "Pet DOB required to generate plan")
    return {"plan_id": plan_id, "status": "SUGGESTED"}


@router.post("/records", response_model=CreateVaccinationRecordOut)
def create_record(
    payload: CreateVaccinationRecordIn,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, payload.pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")

    vacc = _resolve_vaccine_id(
        db,
        vaccine_id=payload.vaccine_id,
        vaccine_code=payload.vaccine_code,
        vaccine_species=payload.vaccine_species,
    )

    row = db.execute(
        text("""
            INSERT INTO vaccination_record
              (pet_id, vaccine_id, vaccine_code, vaccine_species,
               vaccine_type, last_given, next_due, notes, batch_no, manufacturer,
               created_at, updated_at)
            VALUES
              (:pet_id, :vaccine_id, :code, :species,
               :vtype, :last_given, :next_due, :notes, :batch_no, :manufacturer,
               now(), now())
            RETURNING id
        """),
        {
            "pet_id": payload.pet_id,
            "vaccine_id": int(vacc["id"]),
            "code": vacc["code"],
            "species": vacc["species"],
            "vtype": payload.vaccine_type,
            "last_given": payload.last_given,
            "next_due": payload.next_due,
            "notes": payload.notes,
            "batch_no": payload.batch_no,
            "manufacturer": payload.manufacturer,
        },
    ).mappings().first()
    record_id = int(row["id"])

    _get_or_create_plan(db, payload.pet_id)
    _complete_matching_plan_item(
        db,
        pet_id=payload.pet_id,
        vaccine_id=int(vacc["id"]),
        last_given=payload.last_given,
        record_id=record_id,
    )

    db.commit()
    return {"id": record_id}


@router.get("/records")
def list_records(
    pet_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])
    pet = _get_pet(db, pet_id)
    if int(pet["user_id"]) != user_id:
        raise HTTPException(403, "Not your pet")
    return {"items": _load_records(db, pet_id)}


@router.post("/intent", response_model=CreateVaccinationIntentOut)
def create_intent(
    payload: CreateVaccinationIntentIn,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    user_id = int(user["id"])

    appt = db.execute(
        text("SELECT id, parent_id, pet_id FROM appointments WHERE id=:id"),
        {"id": payload.appointment_id},
    ).mappings().first()
    if not appt:
        raise HTTPException(404, "Appointment not found")
    if int(appt["parent_id"]) != user_id:
        raise HTTPException(403, "Not your appointment")
    if int(appt["pet_id"]) != int(payload.pet_id):
        raise HTTPException(400, "pet_id mismatch with appointment")

    requested_vaccine_id = None
    if payload.requested_vaccine_id or (payload.requested_vaccine_code and payload.requested_vaccine_species):
        vacc = _resolve_vaccine_id(
            db,
            vaccine_id=payload.requested_vaccine_id,
            vaccine_code=payload.requested_vaccine_code,
            vaccine_species=payload.requested_vaccine_species,
        )
        requested_vaccine_id = int(vacc["id"])

    row = db.execute(
        text("""
            INSERT INTO vaccination_intent
              (appointment_id, pet_id, requested_vaccine_id, requested_action, parent_notes, created_at)
            VALUES
              (:aid, :pid, :vid, :action, :notes, now())
            ON CONFLICT (appointment_id) DO UPDATE SET
              requested_vaccine_id=EXCLUDED.requested_vaccine_id,
              requested_action=EXCLUDED.requested_action,
              parent_notes=EXCLUDED.parent_notes
            RETURNING id
        """),
        {
            "aid": payload.appointment_id,
            "pid": payload.pet_id,
            "vid": requested_vaccine_id,
            "action": payload.requested_action,
            "notes": payload.parent_notes,
        },
    ).mappings().first()

    db.commit()
    return {"id": int(row["id"])}

# ---------------------------
# Vet endpoints
# ---------------------------

@router.get("/vet/requests", response_model=VetVaccinationRequestsResponse)
def vet_requests(
    day: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    vet_id = int(user["id"])

    rows = db.execute(
        text("""
            SELECT
              a.id AS appointment_id,
              a.start_ts,
              vl.name AS location_name,
              p.id AS pet_id,
              p.name AS pet_name,
              u.name AS owner_name,

              vi.requested_vaccine_id,
              c.code AS requested_vaccine_code,
              c.species AS requested_vaccine_species,

              vi.requested_action,
              pl.status AS plan_status
            FROM appointments a
            JOIN vaccination_intent vi ON vi.appointment_id = a.id
            JOIN pets p ON p.id = a.pet_id
            JOIN users u ON u.id = p.user_id
            LEFT JOIN vet_locations vl ON vl.id = a.location_id
            LEFT JOIN pet_vaccine_plan pl ON pl.pet_id = p.id
            LEFT JOIN vaccine_catalog c ON c.id = vi.requested_vaccine_id
            WHERE a.vet_id = :vet
              AND DATE(a.start_ts AT TIME ZONE 'UTC') = :day
            ORDER BY a.start_ts
        """),
        {"vet": vet_id, "day": day},
    ).mappings().all()

    return {"items": [VetVaccinationRequestItem(**dict(r)) for r in rows]}


@router.get("/vet/appointment/{appointment_id}", response_model=VetAppointmentVaccinationContext)
def vet_appointment_context(
    appointment_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    vet_id = int(user["id"])

    appt = db.execute(
        text("""
            SELECT
              a.id AS appointment_id,
              a.pet_id,
              p.name AS pet_name,
              p.breed,
              p.dob,
              p.species,
              u.name AS owner_name
            FROM appointments a
            JOIN pets p ON p.id = a.pet_id
            JOIN users u ON u.id = p.user_id
            WHERE a.id=:aid AND a.vet_id=:vet
        """),
        {"aid": appointment_id, "vet": vet_id},
    ).mappings().first()
    if not appt:
        raise HTTPException(404, "Appointment not found")

    pet_id = int(appt["pet_id"])

    intent = db.execute(
        text("""
            SELECT
              vi.id,
              vi.requested_vaccine_id,
              c.code AS requested_vaccine_code,
              c.species AS requested_vaccine_species,
              vi.requested_action,
              vi.parent_notes,
              vi.created_at
            FROM vaccination_intent vi
            LEFT JOIN vaccine_catalog c ON c.id = vi.requested_vaccine_id
            WHERE vi.appointment_id=:aid
        """),
        {"aid": appointment_id},
    ).mappings().first()

    plan_id = _get_or_create_plan(db, pet_id)
    plan_status = None
    due_now = []

    if plan_id:
        pl = db.execute(
            text("SELECT status FROM pet_vaccine_plan WHERE id=:id"),
            {"id": plan_id},
        ).mappings().first()
        plan_status = pl["status"] if pl else None
        items = _load_plan_items(db, plan_id)
        due_now = items["due_now"]

    records = _load_records(db, pet_id)[:10]

    return VetAppointmentVaccinationContext(
        appointment_id=appointment_id,
        pet=PetInfo(
            id=pet_id,
            name=appt["pet_name"],
            breed=appt.get("breed"),
            dob=appt.get("dob"),
            species=appt.get("species") or _infer_species_from_pet(appt.get("breed")),
        ),
        owner_name=appt["owner_name"],
        intent=dict(intent) if intent else None,
        plan_status=plan_status,
        due_now=[VaccinePlanItem(**x) for x in due_now],
        records=[VaccinationRecordOut(**r) for r in records],
    )


@router.post("/vet/pets/{pet_id}/plan/confirm", response_model=VetConfirmPlanOut)
def vet_confirm_plan(
    pet_id: int,
    payload: VetConfirmPlanIn,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    vet_id = int(user["id"])
    _get_pet(db, pet_id)  # ensure exists

    plan_id = _get_or_create_plan(db, pet_id)
    if not plan_id:
        raise HTTPException(400, "Pet DOB required to generate plan")

    for o in payload.overrides:
        row = db.execute(
            text("SELECT id FROM pet_vaccine_plan_item WHERE id=:iid AND plan_id=:pid"),
            {"iid": o.plan_item_id, "pid": plan_id},
        ).mappings().first()
        if not row:
            continue

        if o.due_on is not None:
            db.execute(
                text("""
                    UPDATE pet_vaccine_plan_item
                    SET due_on=:due_on,
                        overridden=true,
                        override_reason=:reason
                    WHERE id=:iid
                """),
                {"iid": o.plan_item_id, "due_on": o.due_on, "reason": o.reason},
            )

        if o.status is not None and o.status in ("SKIPPED", "MISSED"):
            db.execute(
                text("""
                    UPDATE pet_vaccine_plan_item
                    SET status=:st,
                        overridden=true,
                        override_reason=:reason
                    WHERE id=:iid AND completed_on IS NULL
                """),
                {"iid": o.plan_item_id, "st": o.status, "reason": o.reason},
            )

    db.execute(
        text("""
            UPDATE pet_vaccine_plan
            SET status='VET_CONFIRMED',
                confirmed_at=now(),
                confirmed_by_vet_id=:vet,
                notes = COALESCE(:notes, notes)
            WHERE id=:pid
        """),
        {"pid": plan_id, "vet": vet_id, "notes": payload.notes},
    )

    db.commit()
    return {"plan_id": plan_id, "status": "VET_CONFIRMED"}


@router.post("/vet/records", response_model=CreateVetVaccinationRecordOut)
def vet_create_record(
    payload: CreateVetVaccinationRecordIn,
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    vet_id = int(user["id"])

    location_id = None
    if payload.appointment_id:
        appt = db.execute(
            text("SELECT id, vet_id, location_id FROM appointments WHERE id=:id"),
            {"id": payload.appointment_id},
        ).mappings().first()
        if not appt:
            raise HTTPException(404, "Appointment not found")
        if int(appt["vet_id"]) != vet_id:
            raise HTTPException(403, "Not your appointment")
        location_id = int(appt["location_id"])

    vacc = _resolve_vaccine_id(
        db,
        vaccine_id=payload.vaccine_id,
        vaccine_code=payload.vaccine_code,
        vaccine_species=payload.vaccine_species,
    )

    row = db.execute(
        text("""
            INSERT INTO vaccination_record
              (pet_id, vaccine_id, vaccine_code, vaccine_species,
               vaccine_type, last_given, next_due,
               batch_no, manufacturer, notes,
               vet_id, location_id, created_at, updated_at)
            VALUES
              (:pet_id, :vaccine_id, :code, :species,
               :vtype, :last_given, :next_due,
               :batch_no, :manufacturer, :notes,
               :vet_id, :loc, now(), now())
            RETURNING id
        """),
        {
            "pet_id": payload.pet_id,
            "vaccine_id": int(vacc["id"]),
            "code": vacc["code"],
            "species": vacc["species"],
            "vtype": payload.vaccine_type,
            "last_given": payload.last_given,
            "next_due": payload.next_due,
            "batch_no": payload.batch_no,
            "manufacturer": payload.manufacturer,
            "notes": payload.notes,
            "vet_id": vet_id,
            "loc": location_id,
        },
    ).mappings().first()
    rid = int(row["id"])

    _get_or_create_plan(db, payload.pet_id)
    _complete_matching_plan_item(
        db,
        pet_id=payload.pet_id,
        vaccine_id=int(vacc["id"]),
        last_given=payload.last_given,
        record_id=rid,
    )

    db.commit()
    return {"id": rid}
