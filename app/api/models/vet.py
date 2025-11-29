from pydantic import BaseModel, Field
from typing import List, Optional

class VetLocationIn(BaseModel):
    name: Optional[str] = None
    line1: Optional[str] = None
    line2: Optional[str] = None
    city: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    hours: Optional[str] = None
    is_primary: Optional[bool] = False


class VetProfileIn(BaseModel):
    # Account
    name: Optional[str] = None
    email: Optional[str] = None

    # Business
    legal_name: Optional[str] = None
    display_name: Optional[str] = None
    business_email: Optional[str] = None
    billing_email: Optional[str] = None
    billing_address: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None

    # Professional
    qualifications: Optional[str] = None
    license_no: Optional[str] = None
    experience_years: Optional[int] = None

    # Specialties (SAFE default)
    specialties: Optional[List[str]] = Field(default=None)

    # Consultation settings (all optional)
    visit_in_clinic: Optional[bool] = None
    visit_video: Optional[bool] = None
    fee_in_clinic: Optional[int] = None
    fee_video: Optional[int] = None
    slot_minutes: Optional[int] = None

    # Locations (SAFE default)
    locations: Optional[List[VetLocationIn]] = Field(default=None)
