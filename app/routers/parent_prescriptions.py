# app/routers/parent_prescriptions.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone, timedelta

from app.dependencies import get_db
from app.routers.security import require_user

from app.api.models.prescriptions import ParentPrescriptionsResponse, RxItem

router = APIRouter(
    prefix="/parents",
    tags=["Parent Prescriptions"],
    dependencies=[Depends(require_user)],
)

def _rx_status(created_at: datetime | None, days: int | None) -> str:
    # If we don't know duration, keep it ACTIVE
    if not created_at or not days or days <= 0:
        return "ACTIVE"
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return "COMPLETED" if created_at + timedelta(days=days) < now else "ACTIVE"


@router.get("/prescriptions/recent", response_model=ParentPrescriptionsResponse)
def get_parent_recent_prescriptions(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_user),
):
    parent_id = int(user["id"])

    rows = db.execute(
        text("""
            SELECT
              m.id                        AS id,
              c.id                        AS consult_id,
              p.id                        AS pet_id,
              p.name                      AS pet_name,
              c.vet_id                    AS vet_id,
              vp.display_name             AS vet_name,
              vl.name                     AS clinic_name,

              m.name                      AS drug,
              m.dose                      AS dose,
              m.frequency                 AS frequency,
              m.days                      AS days,
              m.notes                     AS notes,

              COALESCE(c.created_at, a.start_ts) AS created_at
            FROM consult_medication m
            JOIN consult c           ON c.id = m.consult_id
            JOIN appointments a      ON a.id = c.appointment_id
            JOIN pets p              ON p.id = c.pet_id
            LEFT JOIN vet_profiles vp  ON vp.user_id = c.vet_id
            LEFT JOIN vet_locations vl ON vl.id = a.location_id
            WHERE a.parent_id = :pid
            ORDER BY COALESCE(c.created_at, a.start_ts) DESC, m.id DESC
            LIMIT :limit
        """),
        {"pid": parent_id, "limit": limit},
    ).mappings().all()

    items = []
    for r in rows:
        rr = dict(r)
        rr["status"] = _rx_status(rr.get("created_at"), rr.get("days"))
        items.append(RxItem(**rr))

    return {"items": items}
