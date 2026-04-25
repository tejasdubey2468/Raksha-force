"""
RAKSHA-FORCE — Volunteers API
──────────────────────────────
POST /api/volunteers       → Register as a volunteer
GET  /api/volunteers       → List available volunteers (admin/public)
PATCH /api/volunteers/{id} → Update volunteer status (admin)

─── Example: Register ─────────────────────────────────────────────────────────

POST /api/volunteers
Content-Type: application/json

{
  "name":  "Dr. Priya Patel",
  "phone": "9876543210",
  "city":  "Pune",
  "skill": "doctor"
}

→ 201 Created
{
  "success": true,
  "volunteer_id": "uuid...",
  "message": "Thank you for registering! You will be contacted during emergencies."
}

─── Example: List Volunteers ──────────────────────────────────────────────────

GET /api/volunteers?skill=doctor&city=Pune&limit=20

→ 200 OK
{
  "volunteers": [...],
  "total": 4
}
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from api.utils.auth import optional_auth, require_auth, require_role
from api.utils.db import db_error_response, get_client
from api.utils.logger import get_logger
from api.utils.rate_limit import volunteer_limiter

# ── App ────────────────────────────────────────────────────────

app = FastAPI(title="RAKSHA-FORCE Volunteers API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

log = get_logger("volunteers")

VALID_SKILLS = {
    "doctor", "nurse", "paramedic", "firefighter", "police",
    "ndrf_trained", "flood_rescue", "counselor", "driver",
    "translator", "logistics", "other",
}

VALID_STATUSES = {"available", "busy", "inactive"}


# ── Schemas ────────────────────────────────────────────────────

class VolunteerRegisterRequest(BaseModel):
    name:  str = Field(..., min_length=2, max_length=200)
    phone: str = Field(..., min_length=6, max_length=20)
    city:  str = Field(..., min_length=2, max_length=100)
    skill: str = Field(..., description=f"One of: {', '.join(sorted(VALID_SKILLS))}")

    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_SKILLS:
            raise ValueError(
                f"Invalid skill '{v}'. Valid skills: {', '.join(sorted(VALID_SKILLS))}"
            )
        return v

    @field_validator("name", "city")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) < 6:
            raise ValueError("Phone number too short.")
        return v.strip()


class VolunteerUpdateRequest(BaseModel):
    status: str | None = Field(None)
    city:   str | None = Field(None, max_length=100)
    skill:  str | None = Field(None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(VALID_STATUSES)}")
        return v

    @field_validator("skill")
    @classmethod
    def validate_skill(cls, v):
        if v and v.lower() not in VALID_SKILLS:
            raise ValueError(f"Invalid skill.")
        return v.lower() if v else v


# ── Handlers ───────────────────────────────────────────────────

@app.post("/api/volunteers", status_code=status.HTTP_201_CREATED)
async def register_volunteer(request: Request):
    """
    Register a new volunteer.
    - Public endpoint (no auth required — open registration)
    - Rate limited: 3 registrations per hour per IP
    - Checks for duplicate phone number to prevent double-registration
    """
    client_ip = request.client.host or "unknown"
    allowed, retry_after = volunteer_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many registrations. Wait {retry_after}s.",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = VolunteerRegisterRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    sb = get_client()

    # Duplicate phone check
    try:
        existing = (
            sb.table("volunteers")
            .select("id, name")
            .eq("phone", payload.phone)
            .maybe_single()
            .execute()
        )
        if existing.data:
            raise HTTPException(
                status_code=409,
                detail=f"Phone {payload.phone} is already registered as a volunteer.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Best-effort duplicate check

    try:
        result = sb.table("volunteers").insert({
            "name":   payload.name,
            "phone":  payload.phone,
            "city":   payload.city,
            "skill":  payload.skill,
            "status": "available",
        }).execute()
    except Exception as e:
        log.error("Volunteer insert failed", error=str(e))
        raise HTTPException(status_code=500, detail=db_error_response(e)["error"])

    volunteer = result.data[0] if result.data else {}
    vol_id    = volunteer.get("id", "unknown")

    log.info("Volunteer registered", id=vol_id, skill=payload.skill, city=payload.city)

    return {
        "success":      True,
        "volunteer_id": vol_id,
        "message":      (
            f"Thank you, {payload.name}! You are registered as a '{payload.skill}' volunteer in {payload.city}. "
            "You may be contacted during local emergencies."
        ),
    }


@app.get("/api/volunteers")
async def list_volunteers(request: Request):
    """
    List volunteers. Public endpoint — no auth required.
    Admins see all fields; public sees name, skill, city only.

    Query params:
      skill    → filter by skill
      city     → filter by city (case-insensitive prefix)
      status   → filter by status (default: available)
      limit    → max results (default 50, max 200)
    """
    user   = optional_auth(request)
    params = dict(request.query_params)
    limit  = min(int(params.get("limit", 50)), 200)
    status_filter = params.get("status", "available")

    # Field visibility: admins see phone, others don't
    fields = "id, name, skill, city, status, created_at"
    if user and (user.is_admin() or user.is_responder()):
        fields = "*"

    sb = get_client()
    try:
        q = (
            sb.table("volunteers")
            .select(fields)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status_filter:
            q = q.eq("status", status_filter)
        if params.get("skill"):
            q = q.eq("skill", params["skill"].lower())
        if params.get("city"):
            q = q.ilike("city", f"%{params['city']}%")

        result = q.execute()
    except Exception as e:
        log.error("Volunteer list failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch volunteers.")

    return {"volunteers": result.data, "total": len(result.data)}


@app.patch("/api/volunteers/{volunteer_id}")
async def update_volunteer(volunteer_id: str, request: Request):
    """
    Update a volunteer's status, city, or skill.
    Admin only — used to mark volunteers as busy/inactive after dispatch.
    """
    user = require_auth(request)
    require_role(user, "admin")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        update = VolunteerUpdateRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    patch = {k: v for k, v in update.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=422, detail="No fields to update.")

    sb = get_client()
    try:
        result = sb.table("volunteers").update(patch).eq("id", volunteer_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=db_error_response(e)["error"])

    if not result.data:
        raise HTTPException(status_code=404, detail="Volunteer not found.")

    log.info("Volunteer updated", id=volunteer_id, patch=patch, admin=user.user_id)
    return {"success": True, "volunteer_id": volunteer_id, "updated": patch}


@app.get("/api/volunteers/skills")
async def list_skills():
    """Returns the list of valid volunteer skills. Public endpoint."""
    return {"skills": sorted(VALID_SKILLS)}


# ── Vercel handler ─────────────────────────────────────────────
handler = app
