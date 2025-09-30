from __future__ import annotations
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict

router = APIRouter(prefix="/api/v1", tags=["dev-seed"])

# ------------------------------
# In-memory "DB"
# ------------------------------
_id = {"parent": 1, "pet": 1, "appt": 101, "erx": 1, "order": 1001, "delivery": 1, "stay": 1, "product": 501, "walk": 1, "careplan": 1, "consult": 1}

def next_id(key: str) -> int:
    _id[key] += 1
    return _id[key]

PARENTS: List[Dict] = []
APPOINTMENTS: List[Dict] = [
    {"id": 101, "pet_id": 1, "provider_id": 1, "slot_ts": "2025-09-20T09:00:00+05:30", "mode": "inperson", "status": "scheduled"}
]
VET_SLOTS = ["08:00","08:30","09:00","09:30","10:00","10:30"]
VET_QUEUE: List[Dict] = [
    {"id": 1, "pet": "Milo", "owner": "Sam", "triage": "routine", "status": "arrived"},
    {"id": 2, "pet": "Coco", "owner": "Ava", "triage": "urgent", "status": "arrived"},
]
NUTRI_SLOTS = ["08:00","08:30","09:00","09:30"]

WALKS: List[Dict] = [
    {"id": 1, "pet_id": 1, "walker_id": 1, "when": "2025-09-20T10:00:00+05:30", "status": "scheduled"}
]
WALKER_OPEN = { "1": ["08:30", "10:00"] }

STAYS: List[Dict] = [
    {"id": 1, "pet_id": 1, "from": "2025-09-20", "to": "2025-09-21", "status": "active"}
]

ERX: List[Dict] = [
    {"id": 1, "pet_id": 1, "provider_id": 1, "status": "pending", "items": [{"name":"Amoxicillin","dosage":"250mg"}]}
]

PRODUCTS: List[Dict] = [
    {"id": 501, "name": "Omega Chews", "price": 499, "category": "Treats"},
    {"id": 502, "name": "Joint Support", "price": 699, "category": "Health"},
]

VENDOR_ORDERS: List[Dict] = [
    {"id": 1001, "status": "pending", "items": [{"name":"Omega Chews","qty":1}]}
]
ORDERS: List[Dict] = [
    {"id": 2001, "status": "awaiting_fulfillment", "items": [{"name":"Amoxicillin 250mg","qty":1}], "source": "rx"}
]
DELIVERIES: List[Dict] = [
    {"id": 1, "order_id": 1001, "status": "assigned"}
]

CAREPLANS: List[Dict] = []
CONSULTS: List[Dict] = []

CART_ITEMS: List[Dict] = []  # super-light cart to satisfy /cart/items

# ------------------------------
# Auth & Parent (minimal for preview)
# ------------------------------
class ParentIn(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None

@router.post("/auth/otp/request")
def otp_request(body: Dict):
    # pretend we sent an OTP
    phone = body.get("phone")
    if not phone:
        raise HTTPException(400, "phone required")
    return {"ok": True, "sent_to": phone}

@router.post("/parents")
def create_parent(body: ParentIn):
    pid = next_id("parent")
    rec = {"id": pid, **body.dict()}
    PARENTS.append(rec)
    return rec

# ------------------------------
# Appointments
# ------------------------------
@router.get("/appointments")
def list_appointments(owner_id: Optional[int] = None, provider_id: Optional[int] = None, status: Optional[str] = None):
    rows = APPOINTMENTS
    if status:
        rows = [a for a in rows if a["status"] == status]
    return rows

@router.delete("/appointments/{appointment_id}")
def cancel_appt(appointment_id: int):
    for a in APPOINTMENTS:
        if a["id"] == appointment_id:
            a["status"] = "cancelled"
            return a
    raise HTTPException(404, "appointment not found")

@router.post("/appointments/{appointment_id}/reschedule")
def reschedule_appt(appointment_id: int, body: Dict):
    for a in APPOINTMENTS:
        if a["id"] == appointment_id:
            a["slot_ts"] = body.get("proposed_slot") or a["slot_ts"]
            a["status"] = "rescheduled"
            return a
    raise HTTPException(404, "appointment not found")

@router.post("/appointments/{appointment_id}/confirm")
def confirm_appt(appointment_id: int):
    for a in APPOINTMENTS:
        if a["id"] == appointment_id:
            a["status"] = "confirmed"
            return a
    raise HTTPException(404, "appointment not found")

@router.post("/appointments/{appointment_id}/notify")
def notify_appt(appointment_id: int):
    # pretend to send notifications
    return {"ok": True, "appointment_id": appointment_id}

# ------------------------------
# Providers: Slots & Queue (Vet)
# ------------------------------
@router.get("/providers/1/slots")
def vet_slots(date: str = "today"):
    # Dev seed returns just the slot list
    return {"slots": VET_SLOTS}

@router.get("/providers/1/queue")
def vet_queue(date: str = "today"):
    return VET_QUEUE

@router.patch("/queue/{checkin_id}")
def update_queue(checkin_id: int, body: Dict):
    for q in VET_QUEUE:
        if q["id"] == checkin_id:
            q["status"] = body.get("status", q["status"])
            return q
    raise HTTPException(404, "queue item not found")

# Nutritionist schedule
@router.get("/providers/5/slots")
def nutri_slots(date: str = "today"):
    return {"slots": NUTRI_SLOTS, "booked": ["09:00"]}

@router.put("/providers/5/schedule")
def nutri_schedule_put(body: Dict):
    # accept & ignore (dev seed)
    return {"ok": True, "open": body.get("open", [])}

# ------------------------------
# Walker
# ------------------------------
@router.get("/walks")
def list_walks(walker_id: int):
    return [w for w in WALKS if w["walker_id"] == walker_id]

@router.get("/walks/{walk_id}")
def get_walk(walk_id: int):
    for w in WALKS:
        if w["id"] == walk_id:
            return w
    raise HTTPException(404, "walk not found")

@router.patch("/walks/{walk_id}/start")
def start_walk(walk_id: int):
    w = get_walk(walk_id)
    w["status"] = "in_progress"
    return w

@router.patch("/walks/{walk_id}/stop")
def stop_walk(walk_id: int):
    w = get_walk(walk_id)
    w["status"] = "done"
    return w

@router.post("/walks/{walk_id}/media")
def walk_media(walk_id: int, body: Dict):
    # accept media/note; ignore for dev seed
    return {"ok": True}

@router.get("/walkers/{walker_id}/availability")
def walker_availability(walker_id: int):
    return {"slots": VET_SLOTS, "open": WALKER_OPEN.get(str(walker_id), ["08:30","10:00"])}

@router.put("/walkers/{walker_id}/availability")
def put_walker_availability(walker_id: int, body: Dict):
    open_slots = body.get("open", [])
    WALKER_OPEN[str(walker_id)] = open_slots
    return {"ok": True, "open": open_slots}

# ------------------------------
# Hostel / Daycare
# ------------------------------
@router.post("/stays")
def create_stay(body: Dict):
    sid = next_id("stay")
    rec = {"id": sid, "pet_id": int(body.get("pet_id", 0)), "from": body.get("dates", {}).get("from", "2025-09-20"), "to": body.get("dates", {}).get("to", "2025-09-21"), "status": "active"}
    STAYS.append(rec)
    return rec

@router.get("/providers/10/stays")
def list_stays(hostel_id: int = 10, date: str = "today"):
    return STAYS

@router.post("/stays/{stay_id}/report")
def stay_report(stay_id: int, body: Dict):
    return {"ok": True, "stay_id": stay_id}

# ------------------------------
# eRx & Pharmacist
# ------------------------------
@router.get("/erx")
def list_erx(status: str = "pending"):
    return [x for x in ERX if x["status"] == status]

@router.patch("/erx/{erx_id}")
def update_erx(erx_id: int, body: Dict):
    for x in ERX:
        if x["id"] == erx_id:
            x["status"] = body.get("status", x["status"])
            return x
    raise HTTPException(404, "erx not found")

# Pharmacist orders (fulfillment)
@router.get("/orders")
def list_orders(status: Optional[str] = None, owner_id: Optional[int] = None):
    rows = ORDERS
    if status:
        rows = [o for o in rows if o["status"] == status]
    return rows

@router.patch("/orders/{order_id}")
def patch_order(order_id: int, body: Dict):
    for o in ORDERS:
        if o["id"] == order_id:
            o["status"] = body.get("status", o["status"])
            return o
    raise HTTPException(404, "order not found")

# ------------------------------
# Products, Cart (Parent & Vendor)
# ------------------------------
@router.get("/products")
def list_products(category: Optional[str] = None, q: Optional[str] = None, breed: Optional[str] = None, age_months: Optional[int] = None):
    rows = PRODUCTS
    if category:
        rows = [p for p in rows if p.get("category","").lower() == category.lower()]
    if q:
        ql = q.lower()
        rows = [p for p in rows if ql in p["name"].lower()]
    return rows

class ProductIn(BaseModel):
    name: str
    price: float
    category: Optional[str] = None

@router.post("/products")
def create_product(body: ProductIn):
    pid = next_id("product")
    rec = {"id": pid, **body.dict()}
    PRODUCTS.append(rec)
    return rec

@router.post("/catalog/upload")
def upload_catalog(csv: str = Body(..., media_type="text/csv")):
    # extremely naive CSV (header + rows)
    lines = [ln for ln in csv.splitlines() if ln.strip()]
    for row in lines[1:]:
        cols = [c.strip() for c in row.split(",")]
        if not cols:
            continue
        name = cols[0]
        price = float(cols[1]) if len(cols) > 1 and cols[1] else 0
        pid = next_id("product")
        PRODUCTS.append({"id": pid, "name": name, "price": price})
    return {"rows": max(0, len(lines) - 1)}

class CartItemIn(BaseModel):
    product_id: int
    qty: int

@router.post("/cart/items")
def add_cart_item(body: CartItemIn):
    CART_ITEMS.append({"id": len(CART_ITEMS)+1, **body.dict()})
    return {"ok": True}

# Vendor order intake (back office)
@router.get("/vendor/orders")
def vendor_orders(status: str = "pending"):
    return [o for o in VENDOR_ORDERS if o["status"] == status]

@router.patch("/vendor/orders/{order_id}")
def vendor_order_update(order_id: int, body: Dict):
    for o in VENDOR_ORDERS:
        if o["id"] == order_id:
            o["status"] = body.get("status", o["status"])
            return o
    raise HTTPException(404, "vendor order not found")

# ------------------------------
# Deliveries (Vendor/Pharmacy)
# ------------------------------
@router.get("/deliveries")
def list_deliveries(order_id: Optional[int] = None, partner: Optional[str] = None):
    rows = DELIVERIES
    if order_id:
        rows = [d for d in rows if d["order_id"] == order_id]
    return rows

@router.post("/deliveries/assign")
def assign_delivery(body: Dict):
    did = next_id("delivery")
    rec = {"id": did, "order_id": int(body.get("order_id", 0)), "status": "assigned"}
    DELIVERIES.append(rec)
    return rec

# ------------------------------
# Consults & Care Plans (Nutritionist)
# ------------------------------
class ConsultIn(BaseModel):
    appointment_id: Optional[int] = None
    diagnosis: str
    notes: Optional[str] = None
    pet_id: Optional[int] = None

@router.post("/consults")
def create_consult(body: ConsultIn):
    cid = next_id("consult")
    rec = {"id": cid, **body.dict()}
    CONSULTS.append(rec)
    return rec

class CarePlanIn(BaseModel):
    pet_id: int
    provider_id: int
    tasks: List[Dict]

@router.post("/careplans")
def create_careplan(body: CarePlanIn):
    cid = next_id("careplan")
    rec = {"id": cid, **body.dict()}
    CAREPLANS.append(rec)
    return rec
