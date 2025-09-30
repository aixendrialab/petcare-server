from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import Dict, Any
from api.models.appointments import Appointment, AppointmentAudit, Slot
from api.models.prescriptions import Prescription, PrescriptionItem
from api.models.invoices import Invoice, InvoiceItem
from app.dependencies import get_db

router = APIRouter(prefix="/api/v1/parents", tags=["parent"])

@router.get("/{parent_id}/appointments")
def my_appointments(parent_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = db.query(Appointment).filter(Appointment.parent_id == parent_id).order_by(Appointment.start_ts.desc()).all()
    return {"count": len(rows), "items": [{"id": a.id, "calendar_state": a.calendar_state, "visit_state": a.visit_state} for a in rows]}

@router.post("/{parent_id}/appointments")
def book(parent_id: int, slot_id: int, pet_id: int, db: Session = Depends(get_db)):
    s = db.get(Slot, slot_id)
    if not s or s.status != "OPEN": raise HTTPException(status_code=409, detail="slot not available")
    s.status = "BOOKED"
    a = Appointment(slot_id=s.id, vet_id=s.vet_id, location_id=s.location_id, parent_id=parent_id, pet_id=pet_id,
                    mode=s.mode, start_ts=s.start_ts, end_ts=s.end_ts, calendar_state="CONFIRMED")
    db.add(a); db.flush()
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="parent", action="book", details_json={"slot_id": slot_id}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.post("/{parent_id}/appointments/{appointment_id}/cancel")
def cancel(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.calendar_state = "CANCELLED_BY_PARENT"
    if a.slot_id:
        s = db.get(Slot, a.slot_id)
        if s: s.status = "OPEN"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="parent", action="cancel", details_json={}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.post("/{parent_id}/appointments/{appointment_id}/reschedule")
def reschedule(parent_id: int, appointment_id: int, new_slot_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id: raise HTTPException(status_code=404, detail="appointment not found")
    ns = db.get(Slot, new_slot_id)
    if not ns or ns.status != "OPEN": raise HTTPException(status_code=409, detail="new slot not available")
    if a.slot_id:
        os = db.get(Slot, a.slot_id); 
        if os: os.status = "OPEN"
    ns.status = "BOOKED"
    a.slot_id, a.start_ts, a.end_ts, a.mode, a.calendar_state = ns.id, ns.start_ts, ns.end_ts, ns.mode, "CONFIRMED"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="parent", action="reschedule", details_json={"slot_id": new_slot_id}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.get("/{parent_id}/appointments/{appointment_id}/prescription")
def get_rx(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id: raise HTTPException(status_code=404, detail="appointment not found")
    rx = db.query(Prescription).filter(Prescription.appointment_id==appointment_id).one_or_none()
    if not rx: raise HTTPException(status_code=404, detail="not found")
    items = db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id==rx.id).all()
    return {"diagnosis": rx.diagnosis, "items": [{"drug_name": i.drug_name, "dose": i.dose, "frequency": i.frequency, "before_after_food": i.before_after_food} for i in items]}

@router.get("/{parent_id}/appointments/{appointment_id}/invoice")
def get_invoice(parent_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.parent_id != parent_id: raise HTTPException(status_code=404, detail="appointment not found")
    inv = db.query(Invoice).filter(Invoice.appointment_id==appointment_id).one_or_none()
    if not inv: raise HTTPException(status_code=404, detail="not found")
    items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id==inv.id).all()
    return {
        "invoice_no": inv.invoice_no, "subtotal": str(inv.subtotal),
        "tax_cgst": str(inv.tax_cgst), "tax_sgst": str(inv.tax_sgst),
        "tax_igst": str(inv.tax_igst), "total": str(inv.total), "status": inv.status,
        "items": [{"description": i.description, "qty": float(i.qty), "unit_price": float(i.unit_price), "amount": float(i.amount), "tax_rate": float(i.tax_rate)} for i in items]
    }

@router.get("/{parent_id}/vets/nearby")
def nearby(parent_id: int, lat: float, lng: float, limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT vp.display_name, vl.id as location_id, vl.city, vl.lat, vl.lng,
               6371 * acos(
                 cos(radians(:lat))*cos(radians(vl.lat))*cos(radians(vl.lng)-radians(:lng)) +
                 sin(radians(:lat))*sin(radians(vl.lat))
               ) AS distance_km
        FROM vet_locations vl
        JOIN vet_profiles vp ON vp.user_id = vl.user_id
        ORDER BY distance_km ASC
        LIMIT :lim
    """), {"lat": lat, "lng": lng, "lim": limit}).fetchall()
    return {"items": [dict(r._mapping) for r in rows]}
