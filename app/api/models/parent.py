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

class ParentProfileIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    pets: List[ParentPetIn] = Field(default_factory=list)
