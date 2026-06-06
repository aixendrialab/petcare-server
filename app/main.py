from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.db import init_pool, close_pool
from .routers import lot_d, auth, uploads, vet, appointments_v2, vets
from app.routers.slot_settings import router as slot_settings_router  
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

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

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

app.include_router(vet.router, prefix="/api/v1/users/vet", tags=["vet"])
app.include_router(slot_settings_router)                  # router already has prefix="/api/v1"
app.include_router(appointments_v2.router, prefix="/api/v1/appointments", tags=["appointments"])
app.include_router(vets.router, prefix="/api/v1", tags=["vets"])