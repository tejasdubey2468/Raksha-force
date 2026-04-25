"""
RAKSHA-FORCE — Auth API
─────────────────────────
POST /api/auth/register   → Register a new user
POST /api/auth/login      → Sign in and receive JWT
POST /api/auth/logout     → Invalidate session
GET  /api/auth/me         → Return current user profile

Note: Supabase handles the actual auth — these endpoints are thin
wrappers that also manage the `profiles` table.

─── Example: Register ─────────────────────────────────────────────────────────

POST /api/auth/register
Content-Type: application/json

{
  "email": "aryan@raksha.gov.in",
  "password": "SecurePass123!",
  "full_name": "Chief Aryan Sharma",
  "phone": "9876543210",
  "role": "admin"
}

→ 201 Created
{
  "success": true,
  "user_id": "uuid...",
  "message": "Account created. Please verify your email."
}

─── Example: Login ────────────────────────────────────────────────────────────

POST /api/auth/login
Content-Type: application/json

{ "email": "aryan@raksha.gov.in", "password": "SecurePass123!" }

→ 200 OK
{
  "access_token":  "eyJ...",
  "refresh_token": "eyJ...",
  "user": { "id": "uuid", "email": "...", "role": "admin" }
}
"""

import re

import time
import uuid
import jwt

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator

from api.utils.auth import require_auth, JWT_SECRET, JWT_AUDIENCE
from api.utils.db import db_error_response, get_client
from api.utils.logger import get_logger
from api.utils.rate_limit import RateLimiter

# ── App ────────────────────────────────────────────────────────

app = FastAPI(title="RAKSHA-FORCE Auth API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

log = get_logger("auth")

# Rate limiters for auth endpoints
login_limiter    = RateLimiter(max_calls=10, window_seconds=60)   # 10 attempts/min
register_limiter = RateLimiter(max_calls=5,  window_seconds=3600) # 5 registrations/hr

VALID_ROLES = {"citizen", "responder", "admin"}

# Allowed roles that can be self-assigned at registration
# (admin requires out-of-band approval in production)
SELF_ASSIGNABLE_ROLES = {"citizen", "responder"}


# ── Schemas ────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email:     str  = Field(..., description="Valid email address")
    password:  str  = Field(..., min_length=8, description="Min 8 characters")
    full_name: str  = Field(..., min_length=2, max_length=200)
    phone:     str  = Field("", max_length=20)
    role:      str  = Field("citizen", description="citizen | responder | admin")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email address format.")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(VALID_ROLES)}")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if digits and len(digits) < 6:
            raise ValueError("Phone number too short.")
        return v.strip()


class LoginRequest(BaseModel):
    email:    str = Field(...)
    password: str = Field(...)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


# ── Handlers ───────────────────────────────────────────────────

@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request):
    """
    Register a new user.
    - Rate limited: 5 per IP per hour
    - Creates Supabase auth user + profiles row in one operation
    - Admin role requires an additional admin_secret header in production
    """
    client_ip = request.client.host or "unknown"
    allowed, retry_after = register_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many registration attempts. Try again in {retry_after}s.",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = RegisterRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Protect admin role from self-assignment in production
    # (Allow in demo mode — remove this check for full lockdown)
    if payload.role == "admin":
        admin_secret = request.headers.get("X-Admin-Secret", "")
        import os
        expected = os.environ.get("ADMIN_REGISTRATION_SECRET", "DEMO_MODE")
        if expected != "DEMO_MODE" and admin_secret != expected:
            raise HTTPException(
                status_code=403,
                detail="Admin registration requires X-Admin-Secret header.",
            )

    sb = get_client()

    # Create Supabase auth user
    try:
        auth_result = sb.auth.admin.create_user({
            "email":          payload.email,
            "password":       payload.password,
            "user_metadata":  {"full_name": payload.full_name, "role": payload.role},
            "email_confirm":  True,  # auto-confirm in demo mode
        })
    except Exception as e:
        err_msg = str(e).lower()
        if "already registered" in err_msg or "already exists" in err_msg:
            raise HTTPException(status_code=409, detail="Email already registered.")
        log.error("Auth user creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create account.")

    user_id = auth_result.user.id if auth_result.user else None
    if not user_id:
        raise HTTPException(status_code=500, detail="User creation returned empty ID.")

    # Create profile record
    try:
        sb.table("profiles").upsert({
            "id":        user_id,
            "full_name": payload.full_name,
            "phone":     payload.phone,
            "role":      payload.role,
        }).execute()
    except Exception as e:
        log.error("Profile creation failed", error=str(e), user_id=user_id)
        # Auth user was created — profile failure is recoverable; don't block

    log.info("User registered", user_id=user_id, role=payload.role, email=payload.email)

    return {
        "success":  True,
        "user_id":  user_id,
        "message":  "Account created successfully.",
        "role":     payload.role,
    }


@app.post("/api/auth/login")
async def login(request: Request):
    """
    Sign in with email + password via Supabase Auth.
    Returns access_token (JWT) and refresh_token.
    Rate limited: 10 attempts per minute per IP.
    """
    client_ip = request.client.host or "unknown"
    allowed, retry_after = login_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Wait {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = LoginRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    sb = get_client()
    # Real authentication via Supabase
    try:
        result = sb.auth.sign_in_with_password({
            "email":    payload.email,
            "password": payload.password,
        })
    except Exception as e:
        log.warning("Supabase auth failed", email=payload.email, error=str(e))
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    session = result.session
    user    = result.user

    # Fetch profile for role info
    profile = {}
    try:
        p = sb.table("profiles").select("role, full_name, phone").eq("id", user.id).maybe_single().execute()
        profile = p.data or {}
    except Exception:
        pass

    log.info("User logged in", user_id=user.id)

    return {
        "access_token":  session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in":    session.expires_in,
        "user": {
            "id":        user.id,
            "email":     user.email,
            "role":      profile.get("role", user.user_metadata.get("role", "citizen")),
            "full_name": profile.get("full_name", user.user_metadata.get("full_name", "")),
            "phone":     profile.get("phone", ""),
        },
    }


@app.post("/api/auth/logout")
async def logout(request: Request):
    """Sign out the current user (invalidates session server-side)."""
    user = require_auth(request)
    sb   = get_client()

    try:
        sb.auth.admin.sign_out(user.user_id)
    except Exception:
        pass  # Best-effort; client should clear token regardless

    log.info("User logged out", user_id=user.user_id)
    return {"success": True, "message": "Signed out successfully."}


@app.get("/api/auth/me")
async def get_me(request: Request):
    """
    Return the current authenticated user's profile.
    The frontend can call this on load to validate the token and get role.
    """
    user = require_auth(request)
    sb   = get_client()

    try:
        result = (
            sb.table("profiles")
            .select("id, full_name, phone, role, created_at")
            .eq("id", user.user_id)
            .maybe_single()
            .execute()
        )
        profile = result.data or {}
    except Exception:
        profile = {}

    return {
        "user_id":    user.user_id,
        "email":      user.email,
        "role":       profile.get("role", user.role),
        "full_name":  profile.get("full_name", ""),
        "phone":      profile.get("phone", ""),
        "created_at": profile.get("created_at", ""),
    }


# ── Vercel handler ─────────────────────────────────────────────
handler = app
