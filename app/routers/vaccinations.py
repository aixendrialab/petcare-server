from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.dependencies import get_db
from app.routers.security import require_user

router = APIRouter()

@router.get("/history/{pet_id}")
def get_vaccine_history(
    pet_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_user)
):
    rows = db.execute(
        text("""
            SELECT 
                vaccine_name,
                status,
                last_given,
                next_due
            FROM vaccination_record
            WHERE pet_id = :pid
            ORDER BY last_given DESC NULLS LAST
        """),
        {"pid": pet_id},
    ).mappings().all()

    return [
        {
            "name": r["vaccine_name"],
            "status": r["status"],
            "lastGiven": r["last_given"].isoformat() if r["last_given"] else None,
            "nextDue": r["next_due"].isoformat() if r["next_due"] else None,
        }
        for r in rows
    ]
