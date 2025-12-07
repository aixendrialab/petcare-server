from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime

from app.api.models.base import Base

class Medication(BaseModel):
    name: str
    dose: Optional[str] = None
    frequency: Optional[str] = None
    days: Optional[int] = None
    notes: Optional[str] = None

    class Config:
        orm_mode = True


class Vitals(BaseModel):
    weight_kg: Optional[float] = None
    temp_c: Optional[float] = None
    heart_rate: Optional[int] = None
    resp_rate: Optional[int] = None
    notes: Optional[str] = None

    class Config:
        orm_mode = True


class ConsultCreate(BaseModel):
    appointment_id: int
    pet_id: int
    reason: Optional[str] = None
    findings: Optional[str] = None
    diagnosis: Optional[str] = None
    advice: Optional[str] = None
    vitals: Optional[Vitals] = None
    medications: List[Medication] = []


class ConsultOut(BaseModel):
    id: int
    date: str
    reason: Optional[str]
    findings: Optional[str]
    diagnosis: Optional[str]
    advice: Optional[str]
    vitals: Optional[Vitals]
    medications: List[Medication]

    class Config:
        orm_mode = True

class PastConsultSummary(BaseModel):
    id: int
    date: datetime
    reason: str | None = None
    diagnosis: str | None = None
    medications_count: int = 0
    
class ConsultContext(BaseModel):
    appointment: dict
    pet: dict
    history: List[PastConsultSummary]
    vaccines: List[dict]


class VetQueueItem(BaseModel):
    appointment_id: int
    pet_id: int
    pet_name: str
    pet_avatar_url: str | None = None
    start_ts: datetime
    state: str
    owner_name: str
    location_name: str | None = None

    class Config:
        orm_mode = True

class VetRecentConsult(BaseModel):
    consult_id: int
    date: datetime
    pet_id: int
    pet_name: str
    pet_avatar_url: str | None = None
    diagnosis: str | None = None

    class Config:
        orm_mode = True
        
class PastConsultSummary(BaseModel):
    id: int
    date: str
    reason: Optional[str]
    diagnosis: Optional[str]
    medicationsCount: int

    class Config:
        orm_mode = True
        
                
class Consult(Base):
    __tablename__ = "consult"

    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    pet_id = Column(Integer, ForeignKey("pets.id"), nullable=False)
    vet_id = Column(Integer, ForeignKey("vet_profiles.user_id"), nullable=False)

    reason = Column(Text)
    findings = Column(Text)
    diagnosis = Column(Text)
    advice = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vitals = relationship("ConsultVitals", uselist=False, back_populates="consult")
    medications = relationship("ConsultMedication", back_populates="consult")


class ConsultVitals(Base):
    __tablename__ = "consult_vitals"

    id = Column(Integer, primary_key=True)
    consult_id = Column(Integer, ForeignKey("consult.id"), nullable=False)

    weight_kg = Column(Numeric(5, 2))
    temp_c = Column(Numeric(4, 1))
    heart_rate = Column(Integer)
    resp_rate = Column(Integer)
    notes = Column(Text)

    consult = relationship("Consult", back_populates="vitals")


class ConsultMedication(Base):
    __tablename__ = "consult_medication"

    id = Column(Integer, primary_key=True)
    consult_id = Column(Integer, ForeignKey("consult.id"), nullable=False)

    name = Column(String(255), nullable=False)
    dose = Column(String(255))
    frequency = Column(String(255))
    days = Column(Integer)
    notes = Column(Text)

    consult = relationship("Consult", back_populates="medications")

class VetCheckinAppt(BaseModel):
    id: int                  # appointment id
    pet_id: int
    pet_name: str
    parent_name: str
    slot_id: str
    start_ts: datetime
    mode: str
    calendar_state: str
    visit_state: Optional[str] = None
    location_name: Optional[str] = None

    class Config:
        orm_mode = True