from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import (
    PrescriptionCreate, PrescriptionOut,
    MedicationCreate, MedicationOut,
    VaccineCreate, VaccineOut,
    ReportCreate, ReportOut,
    ConsultCreate, ConsultOut,
    InvoiceCreate, InvoiceOut,
)
from typing import List

router = APIRouter()

# Prescriptions
@router.get("/prescriptions", response_model=List[PrescriptionOut])
def list_rx(pet_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Prescription)
    if pet_id: q = q.filter(models.Prescription.pet_id == pet_id)
    return q.order_by(models.Prescription.id.desc()).all()

@router.post("/prescriptions", response_model=PrescriptionOut)
def create_rx(body: PrescriptionCreate, db: Session = Depends(get_db)):
    rx = models.Prescription(pet_id=body.pet_id, provider_id=body.provider_id, items=str(body.items))
    db.add(rx); db.commit(); db.refresh(rx)
    return rx

# Medications
@router.get("/pets/{pet_id}/medications", response_model=List[MedicationOut])
def list_meds(pet_id: int, db: Session = Depends(get_db)):
    return db.query(models.Medication).filter(models.Medication.pet_id == pet_id).all()

@router.post("/pets/{pet_id}/medications", response_model=MedicationOut)
def add_med(pet_id: int, body: MedicationCreate, db: Session = Depends(get_db)):
    med = models.Medication(pet_id=pet_id, name=body.name, schedule=body.schedule)
    db.add(med); db.commit(); db.refresh(med)
    return med

# Vaccines
@router.get("/pets/{pet_id}/vaccines", response_model=List[VaccineOut])
def list_vaccines(pet_id: int, db: Session = Depends(get_db)):
    return db.query(models.Vaccine).filter(models.Vaccine.pet_id == pet_id).all()

@router.post("/pets/{pet_id}/vaccines", response_model=VaccineOut)
def add_vaccine(pet_id: int, body: VaccineCreate, db: Session = Depends(get_db)):
    v = models.Vaccine(pet_id=pet_id, name=body.name, status=body.status, due_on=body.due_on)
    db.add(v); db.commit(); db.refresh(v)
    return v

# Reports
@router.get("/pets/{pet_id}/reports", response_model=List[ReportOut])
def list_reports(pet_id: int, db: Session = Depends(get_db)):
    return db.query(models.Report).filter(models.Report.pet_id == pet_id).all()

@router.post("/pets/{pet_id}/reports", response_model=ReportOut)
def add_report(pet_id: int, body: ReportCreate, db: Session = Depends(get_db)):
    r = models.Report(pet_id=pet_id, title=body.title, file_url=body.file_url)
    db.add(r); db.commit(); db.refresh(r)
    return r

# Consults
@router.post("/consults", response_model=ConsultOut)
def create_consult(body: ConsultCreate, db: Session = Depends(get_db)):
    c = models.Consult(appointment_id=body.appointment_id, diagnosis=body.diagnosis, notes=body.notes)
    db.add(c); db.commit(); db.refresh(c)
    return c

# Invoices
@router.post("/invoices", response_model=InvoiceOut)
def create_invoice(body: InvoiceCreate, db: Session = Depends(get_db)):
    inv = models.Invoice(owner_type=body.owner_type, owner_id=body.owner_id, amount=body.amount, status="unpaid", pdf_url=None)
    db.add(inv); db.commit(); db.refresh(inv)
    return inv

@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return db.get(models.Invoice, invoice_id)
