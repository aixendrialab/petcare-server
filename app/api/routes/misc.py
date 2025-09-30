from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ... import models
from ...schemas import EventOut, AdoptionOut
from typing import List

router = APIRouter()

@router.get("/adoptions", response_model=List[AdoptionOut])
def adoptions(q: str | None = None, db: Session = Depends(get_db)):
    rows = db.execute("select id, org, name, breed, age, notes, status from adoptions order by id desc").mappings().all()
    return list(rows)

@router.get("/events", response_model=List[EventOut])
def events(city: str | None = None, db: Session = Depends(get_db)):
    q = "select id, title, city, starts_at from events"
    if city: q += " where city = :c"
    rows = db.execute(q, {"c": city} if city else {}).mappings().all()
    return list(rows)

@router.get("/me/notification-preferences")
def get_prefs(user_id: int = 1, db: Session = Depends(get_db)):
    row = db.execute("select sms, email, whatsapp from notification_prefs where user_id=:u", {"u": user_id}).mappings().first()
    if not row: return {"sms": True, "email": True, "whatsapp": True}
    return {"sms": bool(row['sms']), "email": bool(row['email']), "whatsapp": bool(row['whatsapp'])}

@router.put("/me/notification-preferences")
def put_prefs(user_id: int = 1, sms: bool = True, email: bool = True, whatsapp: bool = True, db: Session = Depends(get_db)):
    db.execute("delete from notification_prefs where user_id=:u", {"u": user_id})
    db.execute("insert into notification_prefs(user_id, sms, email, whatsapp) values (:u,:s,:e,:w)",
               {"u":user_id, "s":1 if sms else 0, "e":1 if email else 0, "w":1 if whatsapp else 0})
    db.commit(); return {"ok": True}

@router.post("/televisits")
def create_televisit(appointment_id: int):
    return {"televisit_id":"tv_123", "room_id":"room_abc"}

@router.get("/televisits/{televisit_id}")
def get_televisit(televisit_id: str):
    return {"televisit_id": televisit_id, "parent_token":"tok_p", "provider_token":"tok_v"}
