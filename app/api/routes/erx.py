from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter(prefix="/api/v1", tags=["erx"])

class Item(BaseModel): name:str; dosage:str
class ERx(BaseModel): id:int; pet_id:int; provider_id:int; status:str; items:list[Item]
ERXS=[ERx(id=1,pet_id=1,provider_id=1,status="pending",items=[Item(name="Amoxicillin",dosage="250mg")])]

@router.get("/erx")
def list_erx(status:str="pending"): return [x for x in ERXS if x.status==status]

@router.patch("/erx/{erx_id}")
def update_erx(erx_id:int, body:dict):
    x=next(e for e in ERXS if e.id==erx_id); x.status=body.get("status",x.status); return x
