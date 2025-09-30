from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
from app.api.models import Base

class Prescription(Base):
    __tablename__ = "prescriptions"
    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, nullable=False)
    diagnosis = Column(Text)
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id = Column(Integer, primary_key=True)
    prescription_id = Column(Integer, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False)
    drug_name = Column(String, nullable=False)
    dose = Column(String); frequency = Column(String); before_after_food = Column(String)
