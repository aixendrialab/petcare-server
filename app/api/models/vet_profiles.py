from sqlalchemy import Column, Integer, Text, ForeignKey, JSON, TIMESTAMP, func
from app.api.models.base import Base

class VetProfile(Base):
    __tablename__ = "vet_profiles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    legal_name = Column(Text)
    display_name = Column(Text)
    business_email = Column(Text)
    billing_email = Column(Text)
    billing_address = Column(Text)
    gstin = Column(Text)
    pan = Column(Text)

    qualifications = Column(Text)
    license_no = Column(Text)
    experience_years = Column(Integer)

    specialties = Column(JSON, server_default="'[]'::jsonb")

    visit_in_clinic = Column(Integer)
    visit_video = Column(Integer)
    fee_in_clinic = Column(Integer)
    fee_video = Column(Integer)
    slot_minutes = Column(Integer)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
