# routers/uploads.py
from fastapi import APIRouter, UploadFile, File, HTTPException, Header
from uuid import uuid4
from pathlib import Path
import os, shutil

router = APIRouter()
# Vercel's filesystem is read-only; use /tmp for writable storage (ephemeral)
MEDIA_ROOT = Path("/tmp/uploads") if os.getenv("VERCEL") else Path("static/uploads")
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

# On Vercel, VERCEL_URL is auto-set to the deployment hostname (no https://)
_vercel_url = os.getenv("VERCEL_URL")
PUBLIC_BASE = os.getenv("PUBLIC_BASE") or (f"https://{_vercel_url}" if _vercel_url else "http://127.0.0.1:8001")

def require_auth(authorization: str | None):
    if not authorization:
        raise HTTPException(401, "Unauthorized")

@router.post("/uploads/image")
async def upload_image(file: UploadFile = File(...), authorization: str | None = Header(None)):
    require_auth(authorization)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are allowed")

    ext = (file.filename or "jpg").split(".")[-1].lower()
    name = f"{uuid4().hex}.{ext}"
    dest = MEDIA_ROOT / name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    return {"url": f"{PUBLIC_BASE}/static/uploads/{name}"}
