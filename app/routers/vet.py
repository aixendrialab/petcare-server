# app/routers/vet.py
from __future__ import annotations

from http.client import HTTPException
import json
from fastapi import APIRouter, Depends, status
from app.core.db import get_conn
from .security import current_user_id
from app.api.models.vet import VetProfileIn

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from decimal import Decimal
from typing import Dict, Any, Optional
from app.api.models.appointments import Appointment, AppointmentAudit, Slot
from app.api.models.invoices import Invoice, InvoiceItem
from app.api.models.prescriptions import Prescription, PrescriptionItem
from app.utils.invoice import compute_totals
from app.dependencies import get_db

router = APIRouter(dependencies=[Depends(current_user_id)])

@router.get("/profile")
async def get_profile(uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT * FROM vet_profiles WHERE user_id=%s", (uid,))
        prof = await cur.fetchone()
        await cur.execute(
            "SELECT * FROM vet_locations WHERE user_id=%s ORDER BY is_primary DESC, id",
            (uid,),
        )
        locs = await cur.fetchall()
    return {"profile": prof, "locations": locs}

@router.put("/register", status_code=status.HTTP_200_OK)
async def upsert_profile(body: VetProfileIn, uid: int = Depends(current_user_id)):
    # specialties must be json-encoded for the ::jsonb column
    specialties_json = json.dumps(getattr(body, "specialties", []) or [])

    async with get_conn() as conn, conn.cursor() as cur:
        # (optional) update account fields if provided in the same payload
        if getattr(body, "name", None) is not None or getattr(body, "email", None) is not None:
            await cur.execute(
                """
                UPDATE users
                   SET name  = COALESCE(%s, name),
                       email = COALESCE(%s, email),
                       updated_at = now()
                 WHERE id = %s
                """,
                (getattr(body, "name", None), getattr(body, "email", None), uid),
            )

        # ensure role membership (idempotent)
        await cur.execute(
            "INSERT INTO user_roles(user_id, role) VALUES (%s,'vet') ON CONFLICT DO NOTHING",
            (uid,),
        )

        # upsert vet profile (idempotent)
        await cur.execute(
            """
            INSERT INTO vet_profiles(
              user_id, legal_name, display_name, business_email, billing_email, billing_address,
              gstin, pan, qualifications, license_no, experience_years, specialties,
              visit_in_clinic, visit_video, fee_in_clinic, fee_video, slot_minutes
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET
              legal_name=EXCLUDED.legal_name,
              display_name=EXCLUDED.display_name,
              business_email=EXCLUDED.business_email,
              billing_email=EXCLUDED.billing_email,
              billing_address=EXCLUDED.billing_address,
              gstin=EXCLUDED.gstin,
              pan=EXCLUDED.pan,
              qualifications=EXCLUDED.qualifications,
              license_no=EXCLUDED.license_no,
              experience_years=EXCLUDED.experience_years,
              specialties=EXCLUDED.specialties,
              visit_in_clinic=EXCLUDED.visit_in_clinic,
              visit_video=EXCLUDED.visit_video,
              fee_in_clinic=EXCLUDED.fee_in_clinic,
              fee_video=EXCLUDED.fee_video,
              slot_minutes=EXCLUDED.slot_minutes,
              updated_at=now()
            """,
            (
              uid,
              body.legal_name, body.display_name, body.business_email, body.billing_email, body.billing_address,
              body.gstin, body.pan, body.qualifications, body.license_no, body.experience_years, specialties_json,
              body.visit_in_clinic, body.visit_video, body.fee_in_clinic, body.fee_video, body.slot_minutes,
            ),
        )

        # replace locations
        await cur.execute("DELETE FROM vet_locations WHERE user_id=%s", (uid,))
        for loc in body.locations:
            await cur.execute(
                """
                INSERT INTO vet_locations(user_id, name, line1, line2, city, lat, lng, hours, is_primary)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    uid,
                    getattr(loc, "name", None),
                    getattr(loc, "line1", None),
                    getattr(loc, "line2", None),
                    getattr(loc, "city", None),
                    getattr(loc, "lat", None),
                    getattr(loc, "lng", None),
                    getattr(loc, "hours", None),
                    getattr(loc, "is_primary", False),
                ),
            )

        # return fresh data
        await cur.execute("SELECT * FROM vet_profiles WHERE user_id=%s", (uid,))
        prof = await cur.fetchone()
        await cur.execute(
            "SELECT * FROM vet_locations WHERE user_id=%s ORDER BY is_primary DESC, id",
            (uid,),
        )
        locs = await cur.fetchall()

    return {"profile": prof, "locations": locs}

@router.get("/locations")
async def list_locations(uid: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM vet_locations WHERE user_id=%s ORDER BY is_primary DESC, id",
            (uid,),
        )
        rows = await cur.fetchall()
    return rows

@router.get("/{vet_id}/queue")
def queue(vet_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    start = func.date_trunc('day', func.now()); end = start + func.interval('1 day')
    rows = (db.query(Appointment)
              .filter(Appointment.vet_id==vet_id, Appointment.start_ts>=start, Appointment.start_ts<end,
                      Appointment.calendar_state=='CONFIRMED')
              .order_by(Appointment.start_ts.asc()).all())
    groups = {"booked": [], "arrived": [], "in_consultation": [], "completed": []}
    for a in rows:
        groups["arrived" if a.visit_state=="ARRIVED" else
               "in_consultation" if a.visit_state=="IN_CONSULTATION" else
               "completed" if a.visit_state=="CONSULTATION_COMPLETE" else
               "booked"].append(a.id)
    return {"vet_id": vet_id, "groups": groups}

@router.post("/{vet_id}/appointments/{appointment_id}/checkin")
def checkin(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.visit_state = "ARRIVED"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="checkin", details_json={}))
    db.commit(); return {"id": a.id, "visit_state": a.visit_state}

@router.post("/{vet_id}/appointments/{appointment_id}/start")
def start(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.visit_state = "IN_CONSULTATION"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="start_consult", details_json={}))
    db.commit(); return {"id": a.id, "visit_state": a.visit_state}

@router.post("/{vet_id}/appointments/{appointment_id}/complete")
def complete(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.visit_state = "CONSULTATION_COMPLETE"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="complete_consult", details_json={}))
    db.commit(); return {"id": a.id, "visit_state": a.visit_state}

@router.post("/{vet_id}/appointments/{appointment_id}/cancel")
def cancel(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.calendar_state = "CANCELLED_BY_VET"
    if a.slot_id: 
        s = db.get(Slot, a.slot_id); 
        if s: s.status = "OPEN"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="cancel", details_json={}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.post("/{vet_id}/appointments/{appointment_id}/mark-no-show")
def no_show(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    a.calendar_state = "CANCELLED_BY_VET"
    if a.slot_id: 
        s = db.get(Slot, a.slot_id); 
        if s: s.status = "OPEN"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="no_show", details_json={}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.post("/{vet_id}/appointments/{appointment_id}/reschedule")
def vet_reschedule(vet_id: int, appointment_id: int, new_slot_id: int, db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    ns = db.get(Slot, new_slot_id)
    if not ns or ns.status != "OPEN": raise HTTPException(status_code=409, detail="new slot not available")
    if a.slot_id:
        os = db.get(Slot, a.slot_id); 
        if os: os.status = "OPEN"
    ns.status = "BOOKED"
    a.slot_id, a.start_ts, a.end_ts, a.mode, a.calendar_state = ns.id, ns.start_ts, ns.end_ts, ns.mode, "CONFIRMED"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="reschedule", details_json={"slot_id": new_slot_id}))
    db.commit(); return {"id": a.id, "calendar_state": a.calendar_state}

@router.get("/{vet_id}/propose-reschedules")
def propose_reschedules(vet_id: int, location_id: int, mode: str = "in_person", limit: int = 5, db: Session = Depends(get_db)):
    rows = (db.query(Slot).filter(Slot.vet_id==vet_id, Slot.location_id==location_id, Slot.mode==mode, 
                                  Slot.status=="OPEN", Slot.start_ts>=func.now())
                      .order_by(Slot.start_ts.asc()).limit(limit).all())
    return [{"slot_id": s.id, "start_ts": s.start_ts, "end_ts": s.end_ts} for s in rows]

@router.put("/{vet_id}/appointments/{appointment_id}/prescription")
def save_rx(vet_id: int, appointment_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    rx = db.query(Prescription).filter(Prescription.appointment_id==appointment_id).one_or_none()
    if not rx:
        rx = Prescription(appointment_id=appointment_id); db.add(rx); db.flush()
    rx.diagnosis = payload.get("diagnosis"); rx.notes = payload.get("notes")
    db.query(PrescriptionItem).filter(PrescriptionItem.prescription_id==rx.id).delete()
    for it in payload.get("items", []):
        db.add(PrescriptionItem(prescription_id=rx.id, drug_name=it["drug_name"],
                                dose=it.get("dose"), frequency=it.get("frequency"), before_after_food=it.get("before_after_food")))
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="save_prescription", details_json={}))
    db.commit(); return {"appointment_id": appointment_id, "diagnosis": rx.diagnosis, "items": len(payload.get("items", []))}

@router.post("/{vet_id}/appointments/{appointment_id}/invoice")
def build_invoice(vet_id: int, appointment_id: int, payload: Dict[str, Any], db: Session = Depends(get_db)):
    a = db.get(Appointment, appointment_id)
    if not a or a.vet_id != vet_id: raise HTTPException(status_code=404, detail="appointment not found")
    inv = db.query(Invoice).filter(Invoice.appointment_id==appointment_id).one_or_none()
    if inv: raise HTTPException(status_code=409, detail="invoice already exists")
    clinic = db.execute(text("SELECT vp.legal_name, COALESCE(vl.line1,'')||E'\n'||COALESCE(vl.line2,'')||E'\n'||COALESCE(vl.city,'') AS addr, vp.gstin FROM vet_profiles vp JOIN vet_locations vl ON vl.id=:loc AND vp.user_id=:vet"),
                        {"loc": a.location_id, "vet": a.vet_id}).first()
    legal, addr, gstin = (clinic[0] if clinic else "Clinic", clinic[1] if clinic else "Address", clinic[2] if clinic else None)
    last = db.execute(text("SELECT COALESCE(MAX(id),0) FROM invoices")).scalar() or 0
    number = f"INV-{a.location_id}-{str(last+1).zfill(4)}"
    inv = Invoice(appointment_id=appointment_id, vet_id=a.vet_id, location_id=a.location_id,
                  invoice_no=number, bill_to_parent_id=a.parent_id, clinic_legal_name=legal,
                  clinic_address=addr, gstin=gstin)
    db.add(inv); db.flush()
    for it in payload.get("items", []):
        qty = Decimal(str(it.get("qty",1))); unit = Decimal(str(it.get("unit_price",0)))
        db.add(InvoiceItem(invoice_id=inv.id, description=it["description"], qty=qty, unit_price=unit, amount=qty*unit, tax_rate=Decimal(str(it.get("tax_rate", 0.18)))))
    rows = db.execute(text("SELECT qty, unit_price, tax_rate FROM invoice_items WHERE invoice_id=:iid"), {"iid": inv.id}).fetchall()
    items = [{"qty": float(r[0]), "unit_price": float(r[1]), "tax_rate": float(r[2])} for r in rows]
    subtotal, cgst, sgst, igst, total = compute_totals(items, intra_state=True)
    inv.subtotal, inv.tax_cgst, inv.tax_sgst, inv.tax_igst, inv.total, inv.status = subtotal, cgst, sgst, igst, total, "paid"
    db.add(AppointmentAudit(appointment_id=a.id, actor_kind="vet", action="build_invoice", details_json={"invoice_id": inv.id}))
    db.commit(); return {"invoice_id": inv.id, "invoice_no": inv.invoice_no, "total": str(inv.total)}

@router.get("/{vet_id}/appointments/{appointment_id}/invoice.pdf")
def invoice_pdf(vet_id: int, appointment_id: int, db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.appointment_id==appointment_id).one_or_none()
    if not inv: raise HTTPException(status_code=404, detail="invoice not found")
    pdf = b"%PDF-1.4\n% Simple one-line PDF\n%%EOF"
    return StreamingResponse(iter([pdf]), media_type="application/pdf")
