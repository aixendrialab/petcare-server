from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
import traceback

from app.dependencies import get_db
from app.routers.security import require_user
from app.api.models.consult import (
    Consult,
    ConsultCreate,
    ConsultMedication,
    ConsultOut,
    ConsultContext,
    ConsultVitals,
    PastConsultSummary,
    VetCheckinAppt,
    VetQueueItem,
    VetRecentConsult
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/consults",
    tags=["Consults"],
    dependencies=[Depends(require_user)]
)


# ------------------------------------------------------
# 1) Get consultation context (pet summary, appointment summary, history, vaccines)
# ------------------------------------------------------

@router.get("/context", response_model=ConsultContext)
def get_consult_context(
    appointment_id: int = Query(...),
    pet_id: int = Query(...),
    db: Session = Depends(get_db),
    user=Depends(require_user)
):
    vet_id = int(user["id"])
    logger.info(f"📌 Vet {vet_id} loading consult context for pet={pet_id}")

    # 1) appointment summary
    appt = db.execute(
        text("""
            SELECT 
                id, start_ts, end_ts, mode, slot_id, location_id,
                (SELECT name FROM vet_locations WHERE id = location_id) AS location_name
            FROM appointments
            WHERE id = :id AND vet_id = :vet
        """),
        {"id": appointment_id, "vet": vet_id},
    ).mappings().first()

    if not appt:
        raise HTTPException(404, "Appointment not found")

    # 2) pet summary
    pet = db.execute(
        text("""
        SELECT 
            p.id,
            p.name,
            p.breed,
            p.gender,
            p.picture_uri AS avatar_url,
            p.dob,
            u.name AS owner_name
        FROM pets p
        JOIN users u ON u.id = p.user_id   -- owner is stored in pets.user_id
        WHERE p.id = :pid
        LIMIT 1
    """),
    {"pid": pet_id},
    ).mappings().first()


    # 3) consult history
    history_rows = db.execute(
        text("""
            SELECT 
            c.id,
            a.start_ts AS date,
            c.reason,
            c.diagnosis,
            (SELECT COUNT(*) FROM consult_medication m WHERE m.consult_id = c.id) AS medications_count
        FROM consult c
        JOIN appointments a ON a.id = c.appointment_id
        WHERE c.pet_id = :pid
        ORDER BY a.start_ts DESC
    """),
    {"pid": pet_id},
    ).mappings().all()


    # 4) vaccines (simplified)
    vaccines = db.execute(
        text("""
        SELECT 
            id,
            vaccine_name,
            vaccine_type,
            status,
            last_given,
            next_due,
            batch_no,
            manufacturer,
            notes
        FROM vaccination_record
        WHERE pet_id = :pid
        ORDER BY last_given DESC NULLS LAST
    """),
    {"pid": pet_id},
    ).mappings().all()


    return {
        "appointment": dict(appt),
        "pet": dict(pet),
        "history": history_rows,
        "vaccines": vaccines,
    }


# ------------------------------------------------------
# 2) Save consult (new record)
# ------------------------------------------------------
@router.post("", response_model=dict)
def create_consult(
    payload: ConsultCreate,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    vet_id = int(user["id"])
    logger.info(f"📌 Saving new consult by vet {vet_id} for appt={payload.appointment_id}")
    # Check if a consult already exists (draft update)
    existing = db.execute(
        text("SELECT id FROM consult WHERE appointment_id=:a AND pet_id=:p AND vet_id=:v"),
        {"a": payload.appointment_id, "p": payload.pet_id, "v": vet_id},
    ).mappings().first()

    if existing:
        consult_id = existing["id"]
        # Update draft fields only
        db.execute(
            text("""
                UPDATE consult SET
                    reason=:r,
                    findings=:f,
                    diagnosis=:d,
                    advice=:a,
                    updated_at=NOW()
                WHERE id=:id
            """),
            {"id": consult_id, "r": payload.reason, "f": payload.findings,
             "d": payload.diagnosis, "a": payload.advice}
        )
        db.commit()
        return {"consult_id": consult_id, "status": "saved"}
    
    try:
        consult = Consult(
            appointment_id=payload.appointment_id,
            pet_id=payload.pet_id,
            vet_id=vet_id,
            reason=payload.reason,
            findings=payload.findings,
            diagnosis=payload.diagnosis,
            advice=payload.advice,
        )
        db.add(consult)
        db.flush()  # get consult.id

        # vitals
        if payload.vitals:
            vit = ConsultVitals(
                consult_id=consult.id,
                weight_kg=payload.vitals.weight_kg,
                temp_c=payload.vitals.temp_c,
                heart_rate=payload.vitals.heart_rate,
                resp_rate=payload.vitals.resp_rate,
                notes=payload.vitals.notes,
            )
            db.add(vit)

        # medications
        for med in payload.medications:
            db.add(ConsultMedication(
                consult_id=consult.id,
                name=med.name,
                dose=med.dose,
                frequency=med.frequency,
                days=med.days,
                notes=med.notes
            ))

        # 🔹 mark appointment completed
        #db.execute(
        #    text("""
        #        UPDATE appointments
        #        SET calendar_state = 'COMPLETED',
        #            completed_at   = NOW()
        #        WHERE id = :id
        #    """),
        #    {"id": payload.appointment_id},
        #)

        db.commit()
        db.refresh(consult)

        return {"consult_id": consult.id}

    except Exception as e:
        logger.exception("❌ Error creating consult")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------
# 3) Get detailed past consult (used by PastConsultDetailScreen)
# ------------------------------------------------------
@router.get("/past/{consult_id}", response_model=ConsultOut)
def get_past_consult(
    consult_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    vet_id = int(user["id"])

    row = db.execute(
        text("""
            SELECT c.id,
                   a.start_ts AS date,
                   c.reason,
                   c.findings,
                   c.diagnosis,
                   c.advice
            FROM consult c
            JOIN appointments a ON a.id = c.appointment_id
            WHERE c.id = :cid AND c.vet_id = :vet
        """),
        {"cid": consult_id, "vet": vet_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Consult not found")

    vitals = db.query(ConsultVitals).filter_by(consult_id=consult_id).first()
    meds = db.query(ConsultMedication).filter_by(consult_id=consult_id).all()

    return {
        **row,
        "date": row["date"].isoformat(),   # <-- FIX HERE
        "vitals": vitals,
        "medications": meds,
    }

@router.get("/queue", response_model=list[VetQueueItem])
def get_vet_queue(
    day: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    """Arrived / In-consult patients for this vet for given date."""
    vet_id = int(user["id"])

    rows = db.execute(
        text("""
        SELECT
            a.id                AS appointment_id,
            p.id                AS pet_id,
            p.name              AS pet_name,
            p.picture_uri       AS pet_avatar_url,
            a.start_ts,
            a.calendar_state    AS state,
            u.name              AS owner_name,
            vl.name             AS location_name
        FROM appointments a
        JOIN pets p        ON p.id = a.pet_id
        JOIN users u       ON u.id = p.user_id
        LEFT JOIN vet_locations vl ON vl.id = a.location_id
        WHERE a.vet_id = :vet
          AND DATE(a.start_ts AT TIME ZONE 'UTC') = :day
          AND a.calendar_state IN ('ARRIVED','IN_CONSULT')
        ORDER BY a.start_ts
        """),
        {"vet": vet_id, "day": day},
    ).mappings().all()

    return [VetQueueItem(**row) for row in rows]

@router.get("/history/{pet_id}", response_model=list[PastConsultSummary])
def get_consult_history(
    pet_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_user)
):
    vet_id = int(user["id"])

    rows = db.execute(
        text("""
            SELECT 
                c.id,
                a.start_ts AS date,
                c.reason,
                c.diagnosis,
                (
                    SELECT COUNT(*) 
                    FROM consult_medication m 
                    WHERE m.consult_id = c.id
                ) AS medications_count
            FROM consult c
            JOIN appointments a ON a.id = c.appointment_id
            WHERE c.pet_id = :pid AND c.vet_id = :vet
            ORDER BY a.start_ts DESC
        """),
        {"pid": pet_id, "vet": vet_id},
    ).mappings().all()

    return [
        {
            "id": r["id"],
            "date": r["date"].isoformat(),
            "reason": r["reason"],
            "diagnosis": r["diagnosis"],
            "medicationsCount": r["medications_count"],
        }
        for r in rows
    ]

@router.get("/recent", response_model=list[VetRecentConsult])
def get_vet_recent_consults(
    limit: int = 10,
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    vet_id = int(user["id"])

    rows = db.execute(
        text("""
        SELECT
            c.id           AS consult_id,
            a.start_ts     AS date,
            p.id           AS pet_id,
            p.name         AS pet_name,
            p.picture_uri  AS pet_avatar_url,
            c.diagnosis
        FROM consult c
        JOIN appointments a ON a.id = c.appointment_id
        JOIN pets p         ON p.id = c.pet_id
        WHERE c.vet_id = :vet
        ORDER BY a.start_ts DESC
        LIMIT :limit
        """),
        {"vet": vet_id, "limit": limit},
    ).mappings().all()

    return [VetRecentConsult(**row) for row in rows]

@router.get("/checkin/day", response_model=list[VetCheckinAppt])
def get_checkin_day(
    date: date = Query(default_factory=date.today),
    location_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, description="pet/owner/slot search"),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    print("in get_checkin_day")
    """Appointments for the day for front-desk check-in."""
    vet_id = int(user["id"])
    print(f"vet id is {vet_id}")
    # 🔹 Log incoming params
    print(
        f"[CHECK-IN] Request by vet {vet_id} | day={date} | location={location_id} | search={search}"
    )

    try:
        # ===============================
        # 🔹 EXECUTE QUERY
        # ===============================
        rows = db.execute(
            text("""
                SELECT
                    a.id,
                    a.pet_id,
                    p.name AS pet_name,
                    u.name AS parent_name,
                    a.slot_id,
                    a.start_ts,
                    a.mode,
                    a.calendar_state,
                    a.visit_state,
                    vl.name AS location_name
                FROM appointments a
                JOIN pets p   ON p.id = a.pet_id
                JOIN users u  ON u.id = p.user_id
                LEFT JOIN vet_locations vl ON vl.id = a.location_id
                WHERE DATE(a.start_ts AT TIME ZONE 'UTC') = :day
                  AND a.calendar_state IN ('BOOKED','ARRIVED','IN_CONSULT')
                  AND (:loc IS NULL OR a.location_id = :loc)
                  AND (
                      :search IS NULL
                      OR p.name ILIKE '%' || :search || '%'
                      OR u.name ILIKE '%' || :search || '%'
                      OR a.slot_id ILIKE '%' || :search || '%'
                  )
                ORDER BY a.start_ts
            """),
            {"day": date, "loc": location_id, "search": search},
        ).mappings().all()

        print(f"[CHECK-IN] Found {len(rows)} appointments")

        # 🔹 Convert rows → response model list
        result = [VetCheckinAppt(**row) for row in rows]

        # 🔹 Log final payload (response summary only)
        print(f"[CHECK-IN] Response JSON: {result}")

        return result

    except Exception as e:
        # 🔥 Log full stack trace — server side
        print("[CHECK-IN] ERROR during fetch")
        print(traceback.format_exc())

        # 🔥 Return safe message to client
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load check-in appointments: {str(e)}",
        )
        

@router.post("/complete")
def complete_consult(payload: ConsultCreate, db: Session = Depends(get_db), user=Depends(require_user)):
    vet_id = int(user["id"])

    create_consult(payload, db, user)
    # Reuse save logic + close appointment
    # (You may refactor to avoid duplicate code)

    consult = db.execute(
        text("SELECT id FROM consult WHERE appointment_id=:a"),
        {"a": payload.appointment_id},
    ).mappings().first()

    if not consult:
        raise HTTPException(400, "Save consult before completing")

    consult_id = consult["id"]

    # Complete appointment
    db.execute(
        text("""
            UPDATE appointments
            SET calendar_state='COMPLETED', completed_at=NOW()
            WHERE id=:id
        """),
        {"id": payload.appointment_id},
    )

    db.commit()
    return {"consult_id": consult_id, "status": "completed"}

@router.get("/draft")
def load_consult_draft(
    appointment_id: int = Query(...),
    db: Session = Depends(get_db),
    user = Depends(require_user),
):
    print("load_consult_draft")
    vet_id = int(user["id"])

    print(f"check if draft exists for vet {vet_id}")
    # 1) Load consult row for this appointment if exists
    c = db.execute(
        text("""
            SELECT id, reason, findings, diagnosis, advice
            FROM consult
            WHERE appointment_id = :aid AND vet_id = :vet
        """),
        {"aid": appointment_id, "vet": vet_id},
    ).mappings().first()

    if not c:
        return {}  # No draft yet

    print("draft exists")
    consult_id = c["id"]

    # 2) Load medications
    meds = db.query(ConsultMedication).filter_by(consult_id=consult_id).all()
    meds_list = [
        {
            "name": m.name,
            "dose": m.dose,
            "freq": m.frequency,
            "days": m.days,
        }
        for m in meds
    ]

    # 3) Load vitals (optional)
    vitals = db.query(ConsultVitals).filter_by(consult_id=consult_id).first()
    vitals_data = {
        "weight": getattr(vitals, "weight", None),
        "temperature": getattr(vitals, "temperature", None),
        "heart_rate": getattr(vitals, "heart_rate", None),
    } if vitals else None

    # 4) Map DB → UI expected format
    return {
        "symptoms": c["reason"] or "",
        "notes": c["advice"] or "",
        "diagnosis": c["diagnosis"] or "",
        "medicines": meds_list,
        "vitals": vitals_data,
    }
