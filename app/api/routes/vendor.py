from fastapi import APIRouter, Body
router = APIRouter(prefix="/api/v1", tags=["vendor"])

VENDOR_ORDERS=[{"id":101,"status":"pending","items":[{"name":"Omega Chews","qty":1}]}]
DELIVERIES=[{"id":1,"order_id":101,"status":"assigned"}]

@router.get("/vendor/orders")
def vendor_orders(status:str="pending"): return [o for o in VENDOR_ORDERS if o["status"]==status]

@router.patch("/vendor/orders/{order_id}")
def vendor_order_update(order_id:int, body:dict):
    o=next(o for o in VENDOR_ORDERS if o["id"]==order_id); o["status"]=body.get("status",o["status"]); return o

@router.post("/catalog/upload")
def catalog_upload(csv: str = Body(..., media_type="text/csv")): return {"rows": len(csv.strip().splitlines())-1}

@router.get("/deliveries")
def vendor_deliveries(partner:str="vendor"): return DELIVERIES

@router.post("/deliveries/assign")
def assign_delivery(body:dict):
    i=len(DELIVERIES)+1; DELIVERIES.append({"id":i,"order_id":body["order_id"],"status":"assigned"}); return DELIVERIES[-1]
