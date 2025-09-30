from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter(prefix="/api/v1", tags=["stays"])

class Stay(BaseModel):
    id:int; pet_id:int; from_:str; to:str; status:str
    class Config: fields={'from_':'from'}

STAYS=[Stay(id=1,pet_id=1,from_="2025-09-20",to="2025-09-21",status="active")]

@router.post("/stays")
def create_stay(body:dict):
    i=len(STAYS)+1; STAYS.append(Stay(id=i,pet_id=body["pet_id"],from_="2025-09-20",to="2025-09-21",status="active")); return STAYS[-1]

@router.get("/providers/{hostel_id}/stays")
def list_stays(hostel_id:int, date:str="today"): return STAYS

@router.post("/stays/{stay_id}/report")
def stay_report(stay_id:int, body:dict): return {"ok":True}
