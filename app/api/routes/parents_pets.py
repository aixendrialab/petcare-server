from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import ParentCreate, ParentOut, PetCreate, PetOut
from typing import List

parents = APIRouter()
pets = APIRouter()

@parents.post("", response_model=ParentOut)
def create_parent(payload: ParentCreate, db: Session = Depends(get_db)):
    user = models.User(name=payload.name, phone=payload.phone, email=payload.email or None, role="parent")
    db.add(user); db.flush()
    parent = models.Parent(user_id=user.id, name=payload.name)
    db.add(parent); db.commit(); db.refresh(parent)
    return parent

@parents.get("/{parent_id}", response_model=ParentOut)
def get_parent(parent_id: int, db: Session = Depends(get_db)):
    obj = db.get(models.Parent, parent_id)
    if not obj: raise HTTPException(404, "Parent not found")
    return obj

@pets.post("", response_model=PetOut)
def create_pet(payload: PetCreate, db: Session = Depends(get_db)):
    pet = models.Pet(**payload.model_dump())
    db.add(pet); db.commit(); db.refresh(pet)
    return pet

@pets.get("/{pet_id}", response_model=PetOut)
def get_pet(pet_id: int, db: Session = Depends(get_db)):
    obj = db.get(models.Pet, pet_id)
    if not obj: raise HTTPException(404, "Pet not found")
    return obj

@pets.get("", response_model=List[PetOut])
def list_pets(owner_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Pet)
    if owner_id: q = q.filter(models.Pet.owner_id == owner_id)
    return q.order_by(models.Pet.id.desc()).all()
