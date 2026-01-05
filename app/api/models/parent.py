from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import date

Species = Literal["dog", "cat"]

class ParentPetIn(BaseModel):
    # ✅ allow update existing
    id: Optional[int] = None

    name: str
    breed: Optional[str] = None
    species: Optional[Species] = None

    # keep as string if you prefer; date also works
    dob: Optional[str] = None
    gender: Optional[str] = None
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None

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
    pets: List[ParentPetIn] = Field(default_factory=list)
