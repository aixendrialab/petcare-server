# app/routers/auth.py
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation  # psycopg3
# for psycopg2: from psycopg2.errors import UniqueViolation
from typing import Optional, List, Dict, Any
import os, time, jwt
from ..core.db import get_conn
from typing import List, Optional, Literal

# auth.py  — helpers
from datetime import datetime, timedelta

router = APIRouter()

SECRET = os.getenv("JWT_SECRET", "dev-secret")
ALGO = "HS256"
FIXED_OTP = "123456"
TTL_DAYS = 30

# ---------- Models ----------

class OTPReq(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str

class RegisterParentPet(BaseModel):
    name: str
    breed: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None

class RegisterParent(BaseModel):
    name: str
    email: Optional[str] = None
    pets: List[RegisterParentPet] = Field(default_factory=list)

class RegisterProfile(BaseModel):
    name: str
    email: Optional[str] = None

class RolesIn(BaseModel):
    roles: List[str]  # ["parent","vet",...]

class PetIn(BaseModel):
    name: str
    breed: Optional[str] = None
    dob: Optional[str] = None       # YYYY-MM-DD
    gender: Optional[str] = None    # 'male'|'female'|'unknown'
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None

class PetsUpsert(BaseModel):
    pets: List[PetIn]

class RegisterFull(BaseModel):
    name: str
    email: Optional[str] = None
    pets: List[PetIn]

# ---------- Token helpers ----------

def make_token(phone: str, *, pre: bool, active: dict | None = None) -> str:
    """
    pre=True  -> token for verified-but-not-registered users
    pre=False -> full session token
    """
    payload = {
        "sub": phone,
        "type": "pre" if pre else "actual",
        "exp": datetime.utcnow() + timedelta(days=TTL_DAYS),
    }
    if active:
        payload["active"] = active
    return jwt.encode(payload, SECRET, algorithm=ALGO)

def parse_auth(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- OTP flow ----------

@router.post('/auth/otp/request')
def otp_request(req: OTPReq):
    return {"sent": True}

@router.post("/auth/otp/verify")
async def otp_verify(req: OTPVerify):
    if req.otp != FIXED_OTP:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    phone = (req.phone or "").strip()

    async with get_conn() as conn, conn.cursor() as cur:
        try:
            await cur.execute(
                "INSERT INTO users (phone) VALUES (%s) RETURNING id, active_role",
                (phone,),
            )
            user_id, active_role = await cur.fetchone()
        except UniqueViolation:
            # Already exists → fetch it
            await conn.rollback()  # important before next statement
            async with conn.cursor() as cur2:
                await cur2.execute(
                    "SELECT id, active_role FROM users WHERE phone=%s",
                    (phone,),
                )
                row = await cur2.fetchone()
                if not row:
                    raise HTTPException(500, "Failed to load existing user")
                user_id, active_role = row

        # roles
        await cur.execute(
            "SELECT role FROM user_roles WHERE user_id=%s ORDER BY role",
            (user_id,),
        )
        roles = [{"role": r[0]} for r in await cur.fetchall()]

    token = make_token(phone, pre=False,
                       active={"role": active_role} if active_role else None)
    return {
        "type": "actual",
        "token": token,
        "roles": roles,
        "active": {"role": active_role} if active_role else None,
    }
   
# ---------- Me ----------

@router.get("/me")
async def get_me(authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id, phone, email, name, active_role FROM users WHERE phone=%s", (phone,))
        u = await cur.fetchone()
        if not u:
            #raise HTTPException(status_code=404, detail="User not found")
            return {"user": None, "roles": [], "active": None}
        user = {"id": u[0], "phone": u[1], "email": u[2], "name": u[3]}
        active = {"role": u[4]} if u[4] else None

        await cur.execute("SELECT role FROM user_roles WHERE user_id=%s ORDER BY role", (u[0],))
        roles = [{"role": r[0]} for r in await cur.fetchall()]

        return {"user": user, "roles": roles, "active": active}

@router.get("/auth/me")
async def get_me_alias(authorization: Optional[str] = Header(None)):
    return await get_me(authorization)

# app/auth.py (add next to your existing routes)

class RegisterParentPet(BaseModel):
    name: str
    breed: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    vaccine_status: Optional[str] = None
    rewards: Optional[str] = None
    picture_uri: Optional[str] = None

class RegisterParent(BaseModel):
    name: str
    email: Optional[str] = None
    pets: List[RegisterParentPet] = Field(default_factory=list)

@router.post("/users/register-parent")
async def register_parent(body: RegisterParent, authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims.get("sub")
    if claims.get("type") != "pre" or not phone:  # must be a PRE token
        raise HTTPException(status_code=400, detail="Expected pre-token")

    async with get_conn() as conn:
        async with conn.transaction():
            # Create user (and set active_role to parent)
            row = await conn.execute(
                """
                INSERT INTO users (phone, name, email, active_role)
                VALUES (%s,%s,%s,%s)
                RETURNING id, phone, name, email, active_role
                """,
                (phone, body.name, body.email, "parent")
            )
            user = await row.fetchone()
            user_id = user[0]

            # Attach the parent role (idempotent)
            await conn.execute(
                "INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, "parent")
            )

            # Create pets (*** use the correct FK name: owner_id ***)
            for p in body.pets:
                if not (p.name or "").strip():
                    continue
                await conn.execute(
                    """
                    INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (user_id, p.name, p.breed, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri)
                )

    # Issue ACTUAL token and include roles/active in the response
    roles = [{"role": "parent"}]
    active = {"role": "parent"}
    token = make_token(phone, pre=False, active=active)
    return {
        "type": "actual",
        "token": token,
        "user": {"id": user[0], "phone": user[1], "name": user[2], "email": user[3]},
        "roles": roles,
        "active": active,
    }

# Save profile (name/email). If pre-token, this is where we “complete” registration.
@router.post("/users/register")
async def register_profile(body: RegisterProfile, authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE users SET name=%s, email=%s WHERE phone=%s RETURNING id, active_role", (body.name, body.email, phone))
        u = await cur.fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        # when finishing registration, flip token to actual on client; here we just return state
        await cur.execute("SELECT role FROM user_roles WHERE user_id=%s ORDER BY role", (u[0],))
        roles = [{"role": r[0]} for r in await cur.fetchall()]
        active = {"role": u[1]} if u[1] else None

        await conn.commit()
        return {"ok": True, "roles": roles, "active": active}


@router.post("/users/register-full")
async def register_full(body: RegisterFull, authorization: Optional[str] = Header(None)):
    """
    Completes onboarding for a *new* user (must present a pre-token).
    Creates the user, optional pets, optional roles, and (optionally) sets active role.
    Returns an *actual* token plus user, roles, and active context.
    """
    claims = parse_auth(authorization)
    if not claims or claims.get("type") != "pre":
        # must come with pre-token (verified-but-not-registered)
        raise HTTPException(status_code=400, detail="Expected pre-token")

    phone = claims.get("sub")
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid token")

    # Normalize optional arrays from the body
    pets = getattr(body, "pets", []) or []
    roles_in = getattr(body, "roles", []) or []  # e.g. ["parent","vet"]
    active_role = getattr(body, "active", None)  # e.g. "parent" (optional)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            # 1) Create user
            await cur.execute(
                """
                INSERT INTO users (phone, name, email)
                VALUES (%s, %s, %s)
                RETURNING id, phone, name, email, active_role
                """,
                (phone, body.name, body.email),
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Failed to create user")
            user_id, u_phone, u_name, u_email, _ = row

            # 2) Create pets (ignore blank rows)
            # NOTE: the column is picture_uri (not picture_url).
            for p in pets:
                name = (p.name or "").strip()
                if not name:
                    continue
                await cur.execute(
                    """
                    INSERT INTO pets
                      (owner_user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        name,
                        p.breed,
                        p.dob,
                        p.gender,
                        p.vaccine_status,
                        p.rewards,
                        getattr(p, "picture_uri", None),
                    ),
                )

            # 3) Add roles if provided
            saved_roles: list[dict] = []
            if roles_in:
                # insert each role (ignore duplicates)
                for r in roles_in:
                    await cur.execute(
                        """
                        INSERT INTO user_roles (user_id, role)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING role
                        """,
                        (user_id, r),
                    )
                    ins = await cur.fetchone()
                    # If ON CONFLICT hit, we still want it in output
                    saved_roles.append({"role": ins[0] if ins else r})

            # 4) Resolve active role
            # If caller didn’t specify but exactly one role exists, use it.
            if not active_role:
                if len(saved_roles) == 1:
                    active_role = saved_roles[0]["role"]
                else:
                    # If multiple roles inserted, leave active unset until the user picks
                    active_role = None

            if active_role:
                await cur.execute(
                    "UPDATE users SET active_role=%s WHERE id=%s",
                    (active_role, user_id),
                )

    # 5) Return a real token + shape UI expects
    token = make_token(
        phone,
        pre=False,
        active={"role": active_role} if active_role else None,
    )

    return {
        "type": "actual",
        "token": token,
        "user": {"id": user_id, "phone": u_phone, "name": u_name, "email": u_email},
        "roles": saved_roles,                 # e.g. [{"role":"parent"},{"role":"vet"}]
        "active": {"role": active_role} if active_role else None,
    }

# ---------- Roles ----------

@router.get("/me/roles")
async def get_roles(authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]
        await cur.execute("SELECT role FROM user_roles WHERE user_id=%s ORDER BY role", (user_id,))
        roles = [{"role": r[0]} for r in await cur.fetchall()]
        return {"roles": roles}

@router.post("/me/roles")
async def add_roles(body: RolesIn, authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    roles = body.roles or []
    if not roles:
        return {"roles": []}

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]

        for r in roles:
            await cur.execute("""
              INSERT INTO user_roles (user_id, role)
              VALUES (%s, %s)
              ON CONFLICT (user_id, role) DO NOTHING
            """, (user_id, r))
        await conn.commit()

        await cur.execute("SELECT role FROM user_roles WHERE user_id=%s ORDER BY role", (user_id,))
        out = [{"role": r[0]} for r in await cur.fetchall()]
        return {"roles": out}

# ---------- Active role (context) ----------

@router.post("/me/active")
async def set_active_role(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    role = (payload or {}).get("role")
    if not role:
        raise HTTPException(status_code=400, detail="role required")

    async with get_conn() as conn, conn.cursor() as cur:
        # find user
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]

        # ensure the role exists for this user (idempotent upsert)
        await cur.execute("""
          INSERT INTO user_roles (user_id, role)
          VALUES (%s, %s)
          ON CONFLICT (user_id, role) DO NOTHING
        """, (user_id, role))

        # set active
        await cur.execute(
            "UPDATE users SET active_role=%s WHERE id=%s RETURNING active_role",
            (role, user_id)
        )
        active_role = (await cur.fetchone())[0]

        # fetch roles for response shape the tests expect
        await cur.execute("SELECT role FROM user_roles WHERE user_id=%s ORDER BY role", (user_id,))
        roles = [{"role": r[0]} for r in await cur.fetchall()]

        await conn.commit()

    return {"roles": roles, "active": {"role": active_role}}

# ---------- Pets (array upserts & list & replace & delete) ----------

@router.get("/me/pets")
async def list_pets(authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]
        await cur.execute("""
          SELECT id, name, breed, dob, gender, vaccine_status, rewards, picture_uri
          FROM pets WHERE user_id=%s ORDER BY id
        """, (user_id,))
        pets = []
        for p in await cur.fetchall():
            pets.append({
                "id": p[0], "name": p[1], "breed": p[2],
                "dob": p[3].isoformat() if p[3] else None,
                "gender": p[4], "vaccine_status": p[5],
                "rewards": p[6], "picture_uri": p[7],
            })
        return {"pets": pets}

@router.post("/me/pets")
async def add_pets(body: PetsUpsert, authorization: Optional[str] = Header(None)):
    """
    Accepts { pets: [ {name, breed, ...}, ... ] } and inserts all.
    """
    claims = parse_auth(authorization)
    phone = claims["sub"]
    pets = body.pets or []
    if not pets:
        return {"pets": []}

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]

        for p in pets:
            await cur.execute("""
              INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, p.name, p.breed, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri))
        await conn.commit()

    return await list_pets(authorization)

@router.put("/me/pets")
async def replace_pets(body: PetsUpsert, authorization: Optional[str] = Header(None)):
    """
    Replaces all pets with the provided array.
    """
    claims = parse_auth(authorization)
    phone = claims["sub"]
    new_pets = body.pets or []

    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]

        await cur.execute("DELETE FROM pets WHERE user_id=%s", (user_id,))
        for p in new_pets:
            await cur.execute("""
              INSERT INTO pets (user_id, name, breed, dob, gender, vaccine_status, rewards, picture_uri)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, p.name, p.breed, p.dob, p.gender, p.vaccine_status, p.rewards, p.picture_uri))
        await conn.commit()

    return await list_pets(authorization)

@router.delete("/me/pets/{pet_id}")
async def delete_pet(pet_id: int, authorization: Optional[str] = Header(None)):
    claims = parse_auth(authorization)
    phone = claims["sub"]
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user_id = row[0]

        await cur.execute("DELETE FROM pets WHERE id=%s AND user_id=%s", (pet_id, user_id))
        await conn.commit()
    return {"ok": True}
