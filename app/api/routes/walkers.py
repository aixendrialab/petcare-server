from fastapi import APIRouter
from pydantic import BaseModel
router = APIRouter(prefix="/api/v1", tags=["walkers"])

SLOTS = ["08:00","08:30","09:00","09:30","10:00","10:30"]
OPEN = {"1": ["08:30","10:00"]}

class Avail(BaseModel): slots:list[str]; open:list[str]

@router.get("/walkers/{walker_id}/availability", response_model=Avail)
def get_avail(walker_id:int): return {"slots":SLOTS, "open": OPEN.get(str(walker_id), [])}

class AvailIn(BaseModel): open:list[str]
@router.put("/walkers/{walker_id}/availability")
def put_avail(walker_id:int, body:AvailIn): OPEN[str(walker_id)]=body.open; return {"ok":True}
