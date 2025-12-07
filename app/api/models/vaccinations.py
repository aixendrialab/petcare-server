from sqlalchemy import Column, Integer, Text, Date, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship
from app.core.db import Base
from pydantic import BaseModel
from typing import Optional
from datetime import date


class VaccinationRecord(Base):
    __tablename__ = "vaccination_record"

    id = Column(Integer, primary_key=True)
    pet_id = Column(Integer, ForeignKey("pets.id"), nullable=False)
    vaccine_name = Column(Text, nullable=False)
    vaccine_type = Column(Text)
    last_given = Column(Date)
    next_due = Column(Date)
    status = Column(Text)
    batch_no = Column(Text)
    manufacturer = Column(Text)
    notes = Column(Text)
    vet_id = Column(Integer, ForeignKey("users.id"))
    location_id = Column(Integer, ForeignKey("vet_locations.id"))
    created_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP)

    pet = relationship("Pet", backref="vaccinations")


class VaccinationRecordIn(BaseModel):
    pet_id: int
    vaccine_name: str
    vaccine_type: Optional[str] = None
    last_given: Optional[date] = None
    next_due: Optional[date] = None
    status: Optional[str] = "UPCOMING"
    batch_no: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: Optional[str] = None

class VaccinationRecordOut(BaseModel):
    id: int
    vaccine_name: str
    vaccine_type: Optional[str]
    last_given: Optional[date]
    next_due: Optional[date]
    status: Optional[str]
    batch_no: Optional[str]
    manufacturer: Optional[str]
    notes: Optional[str]

    class Config:
        orm_mode = True
