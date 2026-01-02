from __future__ import annotations

from sqlalchemy import Column, Integer, Text, Date, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship
from app.api.models.base import Base

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Literal
from datetime import date, datetime

# -----------------------
# Shared enums / literals
# -----------------------

PlanStatus = Literal["SUGGESTED", "VET_CONFIRMED"]
PlanItemStatus = Literal["DUE", "UPCOMING", "COMPLETED", "MISSED", "SKIPPED"]
RequestedAction = Literal["ADMINISTER", "CONFIRM_PLAN", "BOTH"]
Species = Literal["dog", "cat"]

# =======================
# SQLAlchemy ORM MODELS
# =======================

# NOTE:
# Schema changed to use vaccine_catalog.id as FK everywhere (vaccine_id).
# We keep vaccine_code + vaccine_species snapshot fields for convenience/debug/history.

class VaccineCatalog(Base):
    __tablename__ = "vaccine_catalog"

    id = Column(Integer, primary_key=True)
    code = Column(Text, nullable=False)
    species = Column(Text, nullable=False)  # 'dog' | 'cat'
    name = Column(Text, nullable=False)
    vaccine_type = Column(Text, nullable=False, default="core")  # 'core'|'optional'
    description = Column(Text)
    is_active = Column(Integer, nullable=False, default=1)  # boolean in DB; Integer ok, but ideally Boolean

    # If you prefer strict boolean mapping, change is_active to:
    # from sqlalchemy import Boolean
    # is_active = Column(Boolean, nullable=False, default=True)


class VaccinationRecord(Base):
    __tablename__ = "vaccination_record"

    id = Column(Integer, primary_key=True)

    pet_id = Column(Integer, ForeignKey("pets.id"), nullable=False)

    # NEW: numeric FK
    vaccine_id = Column(Integer, ForeignKey("vaccine_catalog.id", ondelete="RESTRICT"), nullable=False)

    # snapshot fields (kept in sync via trigger in schema)
    vaccine_code = Column(Text, nullable=False)
    vaccine_species = Column(Text, nullable=False)

    vaccine_type = Column(Text)
    last_given = Column(Date)
    next_due = Column(Date)

    batch_no = Column(Text)
    manufacturer = Column(Text)
    notes = Column(Text)

    vet_id = Column(Integer, ForeignKey("vet_profiles.user_id"))
    location_id = Column(Integer, ForeignKey("vet_locations.id"))

    created_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP)

    pet = relationship("Pet", backref="vaccination_records")
    vaccine = relationship("VaccineCatalog")


class PetVaccinePlan(Base):
    __tablename__ = "pet_vaccine_plan"

    id = Column(Integer, primary_key=True)
    pet_id = Column(Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)

    status = Column(Text, nullable=False, default="SUGGESTED")  # 'SUGGESTED'|'VET_CONFIRMED'
    generated_at = Column(TIMESTAMP)
    confirmed_at = Column(TIMESTAMP)
    confirmed_by_vet_id = Column(Integer, ForeignKey("vet_profiles.user_id"))
    notes = Column(Text)

    pet = relationship("Pet", backref="vaccine_plan")


class PetVaccinePlanItem(Base):
    __tablename__ = "pet_vaccine_plan_item"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("pet_vaccine_plan.id", ondelete="CASCADE"), nullable=False)

    # NEW: numeric FK
    vaccine_id = Column(Integer, ForeignKey("vaccine_catalog.id", ondelete="RESTRICT"), nullable=False)

    # snapshot fields (kept in sync via trigger in schema)
    vaccine_code = Column(Text, nullable=False)
    vaccine_species = Column(Text, nullable=False)

    dose_no = Column(Integer, nullable=False, default=1)
    due_on = Column(Date, nullable=False)

    status = Column(Text, nullable=False, default="UPCOMING")  # DUE|UPCOMING|COMPLETED|MISSED|SKIPPED
    completed_on = Column(Date)
    completed_record_id = Column(Integer, ForeignKey("vaccination_record.id"))

    overridden = Column(Integer, nullable=False, default=0)  # boolean in DB; Integer ok, but ideally Boolean
    override_reason = Column(Text)

    plan = relationship("PetVaccinePlan", backref="items")
    vaccine = relationship("VaccineCatalog")


class VaccinationIntent(Base):
    __tablename__ = "vaccination_intent"

    id = Column(Integer, primary_key=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False)
    pet_id = Column(Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)

    # NEW: points to vaccine_catalog.id
    requested_vaccine_id = Column(Integer, ForeignKey("vaccine_catalog.id", ondelete="RESTRICT"), nullable=True)

    requested_action = Column(Text, nullable=False, default="ADMINISTER")  # ADMINISTER|CONFIRM_PLAN|BOTH
    parent_notes = Column(Text)
    created_at = Column(TIMESTAMP)

    pet = relationship("Pet")
    vaccine = relationship("VaccineCatalog")


class VaccineRule(Base):
    __tablename__ = "vaccine_rule"

    id = Column(Integer, primary_key=True)
    species = Column(Text, nullable=False)  # 'dog'|'cat'

    # NEW: numeric FK
    vaccine_id = Column(Integer, ForeignKey("vaccine_catalog.id", ondelete="CASCADE"), nullable=False)

    start_age_weeks = Column(Integer)
    dose_count = Column(Integer, nullable=False, default=1)
    dose_interval_days = Column(Integer, nullable=False, default=21)
    booster_interval_days = Column(Integer)

    is_active = Column(Integer, nullable=False, default=1)  # boolean in DB; Integer ok, but ideally Boolean

    vaccine = relationship("VaccineCatalog")


# =======================
# Pydantic MODELS
# =======================

class VaccinationRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int

    vaccine_id: int
    vaccine_code: str
    vaccine_species: Species
    vaccine_name: str  # comes from query join in router
    vaccine_type: Optional[str] = None

    last_given: Optional[date] = None
    next_due: Optional[date] = None
    batch_no: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: Optional[str] = None
    vet_id: Optional[int] = None
    location_id: Optional[int] = None
    created_at: Optional[datetime] = None


class VaccineDueItem(BaseModel):
    pet_id: int
    pet_name: str
    plan_item_id: int

    vaccine_id: int
    vaccine_code: str
    vaccine_species: Species
    vaccine_name: str

    dose_no: int
    due_on: date
    status: PlanItemStatus


class VaccinesDueResponse(BaseModel):
    items: List[VaccineDueItem]


class PetVaccineSummary(BaseModel):
    pet_id: int
    pet_name: str
    plan_status: Optional[PlanStatus]
    overdue: int
    due: int
    upcoming: int
    completed: int


class VaccinesSummaryResponse(BaseModel):
    pets: List[PetVaccineSummary]


class VaccinePlanInfo(BaseModel):
    id: int
    status: PlanStatus
    generated_at: datetime
    confirmed_at: Optional[datetime] = None
    confirmed_by_vet_id: Optional[int] = None


class PetInfo(BaseModel):
    id: int
    name: str
    breed: Optional[str] = None
    dob: Optional[date] = None
    species: Species


class VaccinePlanItem(BaseModel):
    id: int

    vaccine_id: int
    vaccine_code: str
    vaccine_species: Species
    vaccine_name: str

    dose_no: int
    due_on: date
    status: PlanItemStatus
    overridden: bool
    override_reason: Optional[str] = None
    completed_on: Optional[date] = None
    completed_record_id: Optional[int] = None


class PetPlanResponse(BaseModel):
    pet: PetInfo
    plan: Optional[VaccinePlanInfo] = None
    due_now: List[VaccinePlanItem]
    upcoming: List[VaccinePlanItem]
    completed: List[VaccinePlanItem]
    records: List[VaccinationRecordOut]


class RecommendedPlanItem(BaseModel):
    vaccine_id: int
    vaccine_code: str
    vaccine_species: Species
    vaccine_name: str

    dose_no: int
    due_on: date
    vaccine_type: Optional[str] = None


class RecommendedPlanResponse(BaseModel):
    pet_id: int
    items: List[RecommendedPlanItem]


class AcceptPlanResponse(BaseModel):
    plan_id: int
    status: PlanStatus


class CreateVaccinationRecordIn(BaseModel):
    pet_id: int

    # With the new schema, prefer vaccine_id.
    # If your UI still sends (code,species), router can resolve -> vaccine_id.
    vaccine_id: Optional[int] = None
    vaccine_code: Optional[str] = None
    vaccine_species: Optional[Species] = None

    last_given: date
    next_due: Optional[date] = None
    vaccine_type: Optional[str] = None
    notes: Optional[str] = None
    batch_no: Optional[str] = None
    manufacturer: Optional[str] = None


class CreateVaccinationRecordOut(BaseModel):
    id: int


class CreateVaccinationIntentIn(BaseModel):
    appointment_id: int
    pet_id: int

    requested_vaccine_id: Optional[int] = None
    requested_vaccine_code: Optional[str] = None
    requested_vaccine_species: Optional[Species] = None

    requested_action: RequestedAction = "ADMINISTER"
    parent_notes: Optional[str] = None


class CreateVaccinationIntentOut(BaseModel):
    id: int


# -------- Vet side --------

class VetVaccinationRequestItem(BaseModel):
    appointment_id: int
    start_ts: datetime
    location_name: Optional[str] = None

    pet_id: int
    pet_name: str
    owner_name: str

    requested_vaccine_id: Optional[int] = None
    requested_vaccine_code: Optional[str] = None
    requested_vaccine_species: Optional[Species] = None

    requested_action: RequestedAction
    plan_status: Optional[PlanStatus] = None


class VetVaccinationRequestsResponse(BaseModel):
    items: List[VetVaccinationRequestItem]


class VetAppointmentVaccinationContext(BaseModel):
    appointment_id: int
    pet: PetInfo
    owner_name: str

    intent: Optional[dict] = None
    plan_status: Optional[PlanStatus] = None

    due_now: List[VaccinePlanItem]
    records: List[VaccinationRecordOut]


class PlanOverrideIn(BaseModel):
    plan_item_id: int
    due_on: Optional[date] = None
    status: Optional[PlanItemStatus] = None
    reason: Optional[str] = None


class VetConfirmPlanIn(BaseModel):
    appointment_id: Optional[int] = None
    notes: Optional[str] = None
    overrides: List[PlanOverrideIn] = []


class VetConfirmPlanOut(BaseModel):
    plan_id: int
    status: PlanStatus


class CreateVetVaccinationRecordIn(BaseModel):
    appointment_id: Optional[int] = None
    pet_id: int

    vaccine_id: Optional[int] = None
    vaccine_code: Optional[str] = None
    vaccine_species: Optional[Species] = None

    last_given: date
    next_due: Optional[date] = None
    vaccine_type: Optional[str] = None
    batch_no: Optional[str] = None
    manufacturer: Optional[str] = None
    notes: Optional[str] = None


class CreateVetVaccinationRecordOut(BaseModel):
    id: int
