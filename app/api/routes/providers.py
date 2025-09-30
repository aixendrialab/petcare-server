from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import ProviderOut, SlotResponse
from typing import List

router = APIRouter()

@router.get("", response_model=List[ProviderOut])
def search_providers(role: str | None = None, q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Provider)
    if role: query = query.filter(models.Provider.role == role)
    if q: query = query.filter(models.Provider.name.ilike(f"%{q}%"))
    return query.order_by(models.Provider.id).all()

@router.get("/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: int, db: Session = Depends(get_db)):
    return db.get(models.Provider, provider_id)

@router.get("/{provider_id}/slots", response_model=SlotResponse)
def get_slots(provider_id: int, date: str | None = None):
    return {"provider_id": provider_id, "date": date, "slots": ["08:00","08:30","09:00","09:30","10:00","10:30"]}

@router.get("/{provider_id}/queue")
def get_queue(provider_id: int, db: Session = Depends(get_db)):
    items = db.execute(
        "select id, appointment_id, pet_id, owner_name, phone, triage, status from checkins order by id desc"
    ).mappings().all()
    return {"provider_id": provider_id, "queue": list(items)}
