from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
router = APIRouter(prefix="/api/v1", tags=["walks"])

class Walk(BaseModel):
    id:int; pet_id:int; walker_id:int; when:str; status:str

WALKS = [Walk(id=1,pet_id=1,walker_id=1,when="2025-09-20T10:00:00+05:30",status="scheduled")]

@router.get("/walks")
def list_walks(walker_id:int): return [w for w in WALKS if w.walker_id==walker_id]

@router.get("/walks/{walk_id}")
def get_walk(walk_id:int): return next(w for w in WALKS if w.id==walk_id)

@router.patch("/walks/{walk_id}/start")
def start_walk(walk_id:int): w=get_walk(walk_id); w.status="in_progress"; return w

@router.patch("/walks/{walk_id}/stop")
def stop_walk(walk_id:int): w=get_walk(walk_id); w.status="done"; return w

class MediaIn(BaseModel): note:Optional[str]=None; photo:Optional[str]=None
@router.post("/walks/{walk_id}/media")
def add_media(walk_id:int, body:MediaIn): return {"ok":True}
