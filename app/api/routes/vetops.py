from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import CheckinCreate, CheckinOut, ConsultCreate, ConsultOut
from typing import List

router = APIRouter()

@router.post("/checkins", response_model=CheckinOut)
def create_checkin(body: CheckinCreate, db: Session = Depends(get_db)):
    c = models.Checkin(appointment_id=body.appointment_id, pet_id=body.pet_id, owner_name=body.owner_name, phone=body.phone, triage=body.triage, status=body.status)
    db.add(c); db.commit(); db.refresh(c); return c

@router.patch("/queue/{checkin_id}", response_model=CheckinOut)
def update_queue(checkin_id: int, status: str, db: Session = Depends(get_db)):
    c = db.get(models.Checkin, checkin_id)
    if not c: raise HTTPException(404, "Not found")
    c.status = status; db.commit(); db.refresh(c); return c

@router.post("/consults", response_model=ConsultOut)
def create_consult(body: ConsultCreate, db: Session = Depends(get_db)):
    c = models.Consult(appointment_id=body.appointment_id, diagnosis=body.diagnosis, notes=body.notes)
    db.add(c); db.commit(); db.refresh(c); return c
