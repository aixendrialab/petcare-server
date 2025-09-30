# app/security.py
from __future__ import annotations
from fastapi import HTTPException, Request
from typing import Optional
import os, jwt
from app.core.db import get_conn  # use the same DB helper as auth.py

ALGO   = "HS256"
SECRET = os.getenv("JWT_SECRET", "dev-secret")

def bearer_token(req: Request) -> Optional[str]:
    h = req.headers.get("authorization") or req.headers.get("Authorization")
    if not h:
        return None
    parts = h.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else None

async def current_user_id(req: Request) -> int:
    """
    Single source of truth for 'who is calling?'.

    Supports:
      1) X-User-Id: <id>                    (tests/dev)
      2) Authorization: Bearer dev-uid:<id> (dev shortcut)
      3) Authorization: Bearer <jwt>        (real token; sub = phone)
      4) request.state.user_id              (middleware/legacy)
    """
    # 1) Explicit header
    xuid = req.headers.get("x-user-id") or req.headers.get("X-User-Id")
    if xuid:
        try:
            return int(xuid)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid X-User-Id header")

    # 2) Dev shortcut
    tok = bearer_token(req)
    if tok and tok.startswith("dev-uid:"):
        try:
            return int(tok.split("dev-uid:", 1)[1])
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid dev token")

    # 3) Real JWT (same secret/alg as auth.py; sub = phone)
    if tok:
        try:
            claims = jwt.decode(tok, SECRET, algorithms=[ALGO])
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
        phone = claims.get("sub")
        if not phone:
            raise HTTPException(status_code=401, detail="Invalid token")

        async with get_conn() as conn, conn.cursor() as cur:
            await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
            row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return int(row[0])

    # 4) Middleware-populated
    if getattr(req.state, "user_id", None):
        return int(req.state.user_id)

    raise HTTPException(status_code=401, detail="Authentication required")
