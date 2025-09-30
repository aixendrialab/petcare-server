from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import AppointmentCreate, AppointmentOut
from typing import List

router = APIRouter()

@router.get("", response_model=List[AppointmentOut])
def list_appointments(provider_id: int | None = None, status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Appointment)
    if provider_id: q = q.filter(models.Appointment.provider_id == provider_id)
    if status: q = q.filter(models.Appointment.status == status)
    return q.order_by(models.Appointment.id.desc()).all()

@router.post("", response_model=AppointmentOut)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    appt = models.Appointment(pet_id=payload.pet_id, provider_id=payload.provider_id, slot_ts=payload.slot, mode=payload.mode, location_id=payload.location_id, status="confirmed")
    db.add(appt); db.commit(); db.refresh(appt)
    return appt

@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt: raise HTTPException(404, "Not found")
    return appt

@router.post("/{appointment_id}/confirm", response_model=AppointmentOut)
def confirm_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt: raise HTTPException(404, "Not found")
    appt.status = "confirmed"
    db.commit(); db.refresh(appt)
    return appt

@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(appointment_id: int, proposed_slot: str, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt: raise HTTPException(404, "Not found")
    appt.slot_ts = proposed_slot; appt.status = "rescheduled"
    db.commit(); db.refresh(appt)
    return appt

@router.delete("/{appointment_id}")
def cancel_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(models.Appointment, appointment_id)
    if not appt: raise HTTPException(404, "Not found")
    db.delete(appt); db.commit()
    return {"ok": True}

@router.post("/{appointment_id}/notify")
def notify(appointment_id: int):
    return {"ok": True, "notified": ["sms","email","whatsapp"]}
