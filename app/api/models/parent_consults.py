from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlalchemy import text
from app.api.models.consult import ConsultMedication, ConsultVitals, Medication, Vitals

class ParentRecentConsult(BaseModel):
    consult_id: int
    date: datetime
    pet_id: int
    pet_name: str
    pet_avatar_url: Optional[str]
    clinic_name: Optional[str]
    vet_name: Optional[str]
    diagnosis: Optional[str]

class ParentConsultDetail(BaseModel):
    consult_id: int
    date: datetime
    pet_name: str
    pet_avatar_url: Optional[str]
    clinic_name: Optional[str]
    vet_name: Optional[str]

    reason: Optional[str]
    symptom_notes: Optional[str] = None  # optional extension later
    findings: Optional[str]
    diagnosis: Optional[str]
    advice: Optional[str]

    vitals: Optional[Vitals]
    medications: List[Medication]
