from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.db import init_pool, close_pool
from app.routers import  addresses, qa, reviews, vendor, appointments, lot_d, auth, uploads, vet,parent, vet_schedule, consult, vaccinations, providers, store, shop, orders, cart, slot_settings, wishlist, parent_prescriptions
from fastapi.staticfiles import StaticFiles

import json
import logging
import time

app = FastAPI(title="PetCare API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup():
    await init_pool()

@app.on_event("shutdown")
async def _shutdown():
    await close_pool()

# Health
@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


logger = logging.getLogger("uvicorn.error")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[REQ] {request.method} {request.url.path} "
          f"qs={dict(request.query_params)} "
          f"hdrs={{'content-type': {request.headers.get('content-type')}, "
          f"'authorization': {bool(request.headers.get('authorization'))}}}")
    start = time.time()
    body_bytes = await request.body()
    # Recreate the body for downstream
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}
    request._receive = receive

    try:
        body_preview = body_bytes.decode("utf-8")[:1000]
    except Exception:
        body_preview = str(body_bytes[:1000])

    logger.info(
        f"[REQ] {request.method} {request.url.path} "
        f"qs={dict(request.query_params)} "
        f"hdrs={{'content-type':{request.headers.get('content-type')}}} "
        f"body={body_preview}"
    )

    response = await call_next(request)
    logger.info(
        f"[RES] {request.method} {request.url.path} -> {response.status_code} "
        f"{round((time.time()-start)*1000)}ms"
    )
    return response


# Include Lot D routes
app.include_router(lot_d.router, prefix="/api/v1", tags=["lot-d"])
app.include_router(auth.router,  prefix="/api/v1", tags=["auth"])

app.include_router(uploads.router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(vet.router, prefix="/api/v1/vet", tags=["vet"])
app.include_router(vet_schedule.router, prefix="/api/v1", tags=["vet"])
app.include_router(parent.router, prefix="/api/v1/parents", tags=["parent"])
app.include_router(slot_settings.router)                  # router already has prefix="/api/v1"
app.include_router(appointments.router, prefix="/api/v1/appointments", tags=["appointments"])
app.include_router(consult.router, prefix="/api/v1")
app.include_router(vaccinations.router, prefix="/api/v1/vaccines", tags=["vaccines"])

app.include_router(addresses.router, prefix="/api/v1", tags=["addresses"])
app.include_router(providers.router, prefix="/api/v1", tags=["providers"])
app.include_router(store.router, prefix="/api/v1", tags=["store"])
app.include_router(shop.router, prefix="/api/v1", tags=["shop"])
app.include_router(orders.router, prefix="/api/v1", tags=["orders"])
app.include_router(cart.router, prefix="/api/v1", tags=["cart"])
app.include_router(vendor.router, prefix="/api/v1", tags=["vendor"])

app.include_router(reviews.router, prefix="/api/v1")
app.include_router(qa.router, prefix="/api/v1")
app.include_router(wishlist.router, prefix="/api/v1")
app.include_router(parent_prescriptions.router, prefix="/api/v1")