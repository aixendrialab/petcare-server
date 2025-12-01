from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
from app.api.models import Base

class Slot(BaseModel):
    """A computed time slice with its availability."""
    start: str
    end: str
    capacity: int
    booked: int = 0
    status: Literal["available", "full", "blocked"] = "available"

class AppointmentCreate(BaseModel):
    vet_id: int
    location_id: int
    #parent_id: int
    pet_id: int
    #slot_id: str
    mode: str = Field(pattern="^(in_person|video)$") 
    start_ts: datetime
    end_ts: datetime

class AppointmentOut(BaseModel):
    id: int
    vet_id: int
    location_id: int
    parent_id: int
    pet_id: int
    slot_id: str
    mode: str
    start_ts: datetime
    end_ts: datetime
    calendar_state: str
    visit_state: Optional[str] = None
    notes: Optional[str] = None
    vet_name: Optional[str] = None
    location_name: Optional[str] = None
    pet_name: Optional[str] = None

    class Config:
        orm_mode = True

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True)
    slot_id = Column(String, nullable=False)
    vet_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    location_id = Column(Integer, ForeignKey("vet_locations.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    pet_id = Column(Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String, nullable=False)
    start_ts = Column(TIMESTAMP(timezone=True), nullable=False)
    end_ts = Column(TIMESTAMP(timezone=True), nullable=False)
    calendar_state = Column(String, nullable=False)
    visit_state = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class AppointmentAudit(Base):
    __tablename__ = "appointment_audit"
    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False)
    at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    actor_kind = Column(String, nullable=False)
    actor_id = Column(Integer, nullable=True)
    action = Column(String, nullable=False)
    details_json = Column(JSON, nullable=False, default={})
