from fastapi import APIRouter
router = APIRouter()

@router.get("")
def list_appointments():
    return []

@router.post("")
def create_appointment():
    return {"ok": True}

@router.post("/{appointment_id}/checkin")
def checkin(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "ARRIVED"}

@router.post("/{appointment_id}/start")
def start_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "IN_CONSULTATION"}

@router.post("/{appointment_id}/complete")
def complete_consult(appointment_id: int):
    return {"ok": True, "appointment_id": appointment_id, "visit_state": "CONSULTATION_COMPLETE"}