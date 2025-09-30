from fastapi import APIRouter
router = APIRouter(prefix="/api/v1/vets", tags=["queue"])

@router.get("/{vet_id}/queue")
def today_queue(vet_id: int):
    return {"vet_id": vet_id, "date": "today", "groups": {"booked": [], "arrived": [], "in_consultation": [], "completed": []}}