# app/models/parent.py
from pydantic import BaseModel, Field
from typing import List, Optional

class ParentPetIn(BaseModel):
    name: str
    breed: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None

    # NEW FIELDS
    microchip: Optional[str] = None
    blood_group: Optional[str] = None
    is_neutered: Optional[bool] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    behavior_notes: Optional[str] = None
    weight_kg: Optional[float] = None
    color_markings: Optional[str] = None


class ParentProfileIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    pets: List[ParentPetIn] = Field(default_factory=list)

class PetsUpsert(BaseModel):
    pets: list[ParentPetIn] = Field(default_factory=list)


class ParentUpcomingAppointment(BaseModel):
    id: int
    pet_id: int
    pet_name: str
    vet_name: str | None
    location_name: str | None
    start_ts: str
    mode: str
    slot_id: int
    calendar_state: str
