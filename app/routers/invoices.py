from fastapi import APIRouter
router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])

@router.get("/{appointment_id}")
def get_invoice(appointment_id: int):
    return {"appointment_id": appointment_id}