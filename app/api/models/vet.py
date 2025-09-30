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
    # NEW: optional account fields to upsert users table
    name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)

    legal_name: Optional[str] = None
    display_name: Optional[str] = None
    business_email: Optional[str] = None
    billing_email: Optional[str] = None
    billing_address: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    qualifications: Optional[str] = None
    license_no: Optional[str] = None
    experience_years: Optional[int] = 0
    specialties: List[str] = []
    visit_in_clinic: bool = True
    visit_video: bool = True
    fee_in_clinic: Optional[int] = 0
    fee_video: Optional[int] = 0
    slot_minutes: int = 15
    locations: List[VetLocationIn] = []
