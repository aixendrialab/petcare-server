# app/routers/security.py
from __future__ import annotations
from fastapi import HTTPException, Request, Depends, status
from typing import Optional, TypedDict
import os, jwt
from app.core.db import get_conn  # your existing DB helper

ALGO   = "HS256"
SECRET = os.getenv("JWT_SECRET", "dev-secret")

# Optional issuer/audience checks if you mint them
JWT_ISS = os.getenv("JWT_ISS")
JWT_AUD = os.getenv("JWT_AUD")

# Allow small clock skew (seconds)
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY", "30"))

class UserPrincipal(TypedDict, total=False):
    id: int
    phone: str
    role: str  # "parent" | "staff" | etc.

def _bearer_token(req: Request) -> Optional[str]:
    """Case-insensitive 'Authorization: Bearer <token>' parser."""
    h = req.headers.get("authorization") or req.headers.get("Authorization")
    if not h:
        return None
    parts = h.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()

async def _lookup_user_id_by_phone(phone: str) -> Optional[int]:
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        return int(row[0]) if row else None

async def _resolve_user_from_headers(req: Request) -> Optional[UserPrincipal]:
    """
    Resolution order (compatible with your current behavior):
      1) X-User-Id: <id>                     (tests/dev)
      2) Authorization: Bearer dev-uid:<id>  (dev shortcut)
      3) Authorization: Bearer <jwt>         (real token; sub=phone, exp required)
      4) request.state.user_id               (middleware/legacy)
    """
    # (1) Explicit user id for tests/dev
    xuid = req.headers.get("x-user-id") or req.headers.get("X-User-Id")
    if xuid:
        try:
            return UserPrincipal(id=int(xuid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-User-Id")

    tok = _bearer_token(req)

    # (2) Dev shortcut
    if tok and tok.startswith("dev-uid:"):
        try:
            return UserPrincipal(id=int(tok.split("dev-uid:", 1)[1]))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev token")

    # (3) Real JWT (strict)
    if tok:
        try:
            options = {"require": ["sub", "exp"], "verify_signature": True}
            decode_kwargs = {
                "key": SECRET,
                "algorithms": [ALGO],          # prevent alg confusion
                "options": options,
                "leeway": JWT_LEEWAY_SECONDS,
            }
            if JWT_ISS:
                decode_kwargs["issuer"] = JWT_ISS
            if JWT_AUD:
                decode_kwargs["audience"] = JWT_AUD

            claims = jwt.decode(tok, **decode_kwargs)
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        phone = claims.get("sub")
        if not phone:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token (sub)")

        uid = await _lookup_user_id_by_phone(phone)
        if not uid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        role = str(claims.get("role", "")).lower() if "role" in claims else ""
        return UserPrincipal(id=uid, phone=phone, role=role)

    # (4) Middleware-populated (legacy)
    if getattr(req.state, "user_id", None):
        return UserPrincipal(id=int(req.state.user_id))

    return None

async def require_user(req: Request) -> UserPrincipal:
    """Use via Depends(require_user) to enforce auth on routes/routers."""
    user = await _resolve_user_from_headers(req)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user

# --- Legacy helpers kept for existing imports in other routers ---

async def current_user_id(user: UserPrincipal = Depends(require_user)) -> int:
    return int(user["id"])

async def current_user(user: UserPrincipal = Depends(require_user)) -> UserPrincipal:
    return user

__all__ = ["require_user", "current_user_id", "current_user", "UserPrincipal"]
