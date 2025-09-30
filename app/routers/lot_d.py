from fastapi import APIRouter, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

router = APIRouter()

# NOTE: These are GET views returning stubbed/dummy data.
# The Postgres schema + seed are provided for future wiring.

def _ts(minutes_ago: int = 0) -> str:
    return (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat() + "Z"

@router.get("/careplans")
def careplans_list(parent_id: Optional[int] = None) -> Dict[str, Any]:
    data = [
        {"id": 1, "pet_id": 101, "title": "Weight Management", "status": "active", "updated_at": _ts(15)},
        {"id": 2, "pet_id": 102, "title": "Post-Op Recovery", "status": "active", "updated_at": _ts(240)},
    ]
    if parent_id:
        data = [d for d in data if d["pet_id"] in (101, 102)]  # demo filter
    return {"items": data}

@router.get("/consults")
def consults_list() -> Dict[str, Any]:
    return {"items": [
        {"id": 501, "pet_id": 101, "vet_id": 901, "mode": "clinic", "at": _ts(60)},
        {"id": 502, "pet_id": 102, "vet_id": 902, "mode": "tele", "at": _ts(280)},
    ]}

@router.get("/labs/orders")
def labs_orders() -> Dict[str, Any]:
    return {"items": [
        {"id": 8001, "pet_id": 101, "test": "CBC", "status": "ordered", "ordered_at": _ts(90)},
        {"id": 8002, "pet_id": 102, "test": "Thyroid", "status": "in-progress", "ordered_at": _ts(300)},
    ]}

@router.get("/labs/results")
def labs_results() -> Dict[str, Any]:
    return {"items": [
        {"order_id": 8001, "result": {"WBC": "6.5", "RBC": "5.1"}, "ready_at": _ts(20)},
    ]}

@router.get("/inventory")
def inventory_list() -> Dict[str, Any]:
    return {"items": [
        {"sku": "MED-001", "name": "Amoxicillin 250mg", "type": "med", "qty": 120, "reorder_level": 40},
        {"sku": "VAC-101", "name": "Rabies Vaccine", "type": "vaccine", "qty": 30, "reorder_level": 10},
        {"sku": "SUP-550", "name": "Bandage Roll", "type": "supply", "qty": 200, "reorder_level": 50},
    ]}

@router.get("/invoices")
def invoices_list(parent_id: Optional[int] = None) -> Dict[str, Any]:
    return {"items": [
        {"id": 9001, "parent_id": 1, "amount": 1200.0, "status": "paid", "at": _ts(300)},
        {"id": 9002, "parent_id": 1, "amount": 650.0, "status": "due", "at": _ts(45)},
    ]}

@router.get("/day-close")
def day_close() -> Dict[str, Any]:
    return {
        "date": datetime.utcnow().date().isoformat(),
        "totals": {"invoices": 24, "revenue": 32500.00, "refunds": 2, "cash": 12000.0, "upi": 9000.0, "card": 11500.0},
    }

@router.get("/staff")
def staff_roster() -> Dict[str, Any]:
    return {"items": [
        {"id": 3001, "name": "Dr. Kannan", "role": "vet", "shift": "09:00-17:00"},
        {"id": 3002, "name": "Revathi", "role": "nurse", "shift": "10:00-18:00"},
        {"id": 3003, "name": "Sanjay", "role": "pharmacist", "shift": "12:00-20:00"},
    ]}

@router.get("/televisits")
def televisits() -> Dict[str, Any]:
    return {"items": [
        {"id": 7001, "pet_id": 101, "parent_id": 1, "status": "scheduled", "at": _ts(120), "link": "https://meet.example/abc"},
        {"id": 7002, "pet_id": 103, "parent_id": 2, "status": "completed", "at": _ts(300), "link": "https://meet.example/def"},
    ]}

@router.get("/chat")
def chat_threads() -> Dict[str, Any]:
    return {"items": [
        {"id": 6001, "members": ["parent:1", "vet:901"], "last_message": "See you at 5pm", "at": _ts(10)},
        {"id": 6002, "members": ["parent:1", "pharmacist:3003"], "last_message": "Invoice shared", "at": _ts(55)},
    ]}

@router.get("/analytics")
def analytics_top() -> Dict[str, Any]:
    return {
        "cards": [
            {"label": "Appointments Today", "value": 18},
            {"label": "Avg Wait (min)", "value": 12},
            {"label": "Televisits", "value": 6},
            {"label": "Revenue (₹)", "value": 32500},
        ],
        "series": [
            {"name": "Appointments", "points": [12, 15, 17, 18, 14, 16, 20]},
            {"name": "Revenue", "points": [22000, 25000, 26000, 32500, 28000, 30000, 35000]},
        ],
    }

@router.get("/notifications/test")
def notifications_test() -> Dict[str, Any]:
    return {"sent": True, "message": "This is a test notification to your device/email."}

# ---------------- Parent read flows ----------------

@router.get("/parent/{parent_id}/book")
def parent_book(parent_id: int) -> Dict[str, Any]:
    return {"appointments": [
        {"id": 10001, "pet_id": 101, "when": _ts(60), "with": "Dr. Kannan", "mode": "clinic", "status": "confirmed"},
        {"id": 10002, "pet_id": 102, "when": _ts(240), "with": "Revathi (Nurse)", "mode": "tele", "status": "scheduled"},
    ]}

@router.get("/parent/{parent_id}/prescriptions")
def parent_prescriptions(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"id": 11001, "pet_id": 101, "text": "Amoxicillin 250mg, 1-0-1 x 5 days"},
        {"id": 11002, "pet_id": 102, "text": "Omeprazole 20mg, 0-0-1 x 7 days"},
    ]}

@router.get("/parent/{parent_id}/meds")
def parent_meds(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"sku": "MED-001", "name": "Amoxicillin 250mg", "qty": 10, "refills": 0},
        {"sku": "MED-010", "name": "Omeprazole 20mg", "qty": 7, "refills": 1},
    ]}

@router.get("/parent/{parent_id}/vaccines")
def parent_vaccines(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"name": "Rabies", "due": "2025-11-01", "last": "2024-11-01"},
        {"name": "DHPP", "due": "2026-02-10", "last": "2025-02-10"},
    ]}

@router.get("/parent/{parent_id}/reports")
def parent_reports(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"id": 12001, "type": "lab", "title": "CBC - Normal", "ready_at": _ts(20)},
        {"id": 12002, "type": "imaging", "title": "X-Ray - Clear", "ready_at": _ts(300)},
    ]}

@router.get("/parent/{parent_id}/cart")
def parent_cart(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"sku": "VAC-101", "name": "Rabies Vaccine", "qty": 1, "price": 450.0},
        {"sku": "SUP-550", "name": "Bandage Roll", "qty": 2, "price": 50.0},
    ], "currency": "INR", "total": 550.0}

@router.get("/parent/{parent_id}/orders")
def parent_orders(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"order_id": 13001, "status": "processing", "total": 1350.0, "placed_at": _ts(180)},
        {"order_id": 13002, "status": "delivered", "total": 820.0, "placed_at": _ts(720)},
    ]}

@router.get("/parent/{parent_id}/rewards")
def parent_rewards(parent_id: int) -> Dict[str, Any]:
    return {"points": 240, "tier": "Silver", "next_tier_at": 500}

@router.get("/parent/{parent_id}/adoption")
def parent_adoption(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"id": 14001, "name": "Lucy", "species": "Dog", "age_months": 6},
        {"id": 14002, "name": "Milo", "species": "Cat", "age_months": 10},
    ]}

@router.get("/parent/{parent_id}/events")
def parent_events(parent_id: int) -> Dict[str, Any]:
    return {"items": [
        {"id": 15001, "title": "Vaccination Camp", "date": "2025-10-15", "location": "Clinic A"},
        {"id": 15002, "title": "Puppy Socialization", "date": "2025-11-02", "location": "Park B"},
    ]}
