"""
RAKSHA-FORCE — GPS Location API
─────────────────────────────────
POST /api/gps        → Upsert (create/update) user's GPS location
GET  /api/gps        → List all active GPS locations (admin: all, citizen: own)
GET  /api/gps/{uid}  → Get specific user's last known location (admin only)

Design:
  - One row per user (upserted on user_id)
  - Validates coordinate ranges
  - Tracks page_context ('citizen'|'admin'|'report')
  - Rate limited: max 60 updates/min (once/second)

─── Example: Update location ──────────────────────────────────────────────────

POST /api/gps
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "latitude": 18.5204,
  "longitude": 73.8567,
  "page_context": "citizen"
}

→ 200 OK
{
  "success": true,
  "user_id": "uuid...",
  "latitude": 18.5204,
  "longitude": 73.8567,
  "updated_at": "2025-01-01T12:00:00Z"
}

─── Example: Get all locations (admin) ────────────────────────────────────────

GET /api/gps
Authorization: Bearer <admin-jwt>

→ 200 OK
{
  "locations": [
    { "user_id": "...", "latitude": 18.52, "longitude": 73.85, "page_context": "citizen", "updated_at": "..." }
  ],
  "total": 3
}
"""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from api.utils.auth import require_auth, require_role
from api.utils.db import db_error_response, get_client
from api.utils.geo import validate_coordinates, validate_india_coordinates
from api.utils.logger import get_logger
from api.utils.rate_limit import gps_limiter

# ── App ────────────────────────────────────────────────────────

app = FastAPI(title="RAKSHA-FORCE GPS API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

log = get_logger("gps")

VALID_CONTEXTS = {"citizen", "admin", "report", "volunteer", "unknown"}


# ── Schemas ────────────────────────────────────────────────────

class GPSUpdateRequest(BaseModel):
    latitude:     float  = Field(..., ge=-90,  le=90)
    longitude:    float  = Field(..., ge=-180, le=180)
    page_context: str    = Field("unknown", description="UI context where GPS is active")
    accuracy:     float  = Field(None, ge=0, description="GPS accuracy in metres (optional)")

    @field_validator("page_context")
    @classmethod
    def validate_context(cls, v: str) -> str:
        v = v.lower().strip()
        return v if v in VALID_CONTEXTS else "unknown"


# ── Handlers ───────────────────────────────────────────────────

@app.post("/api/gps")
async def upsert_gps(request: Request):
    """
    Upsert (insert or update) the authenticated user's GPS location.
    Rate limited: 60 updates per minute per user (≈ 1/sec, matches browser GPS).

    Auth required — anonymous GPS tracking is not supported.
    """
    user = require_auth(request)

    allowed, retry_after = gps_limiter.check(user.user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"GPS update rate limit exceeded. Wait {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = GPSUpdateRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Coordinate validation
    valid, err = validate_coordinates(payload.latitude, payload.longitude)
    if not valid:
        raise HTTPException(status_code=422, detail=f"Invalid coordinates: {err}")

    # Soft-warn if outside India (still accept — users may be on border or VPN)
    india_valid = validate_india_coordinates(payload.latitude, payload.longitude)

    now = datetime.now(timezone.utc).isoformat()
    sb  = get_client()

    try:
        result = sb.table("gps_locations").upsert(
            {
                "user_id":      user.user_id,
                "latitude":     payload.latitude,
                "longitude":    payload.longitude,
                "page_context": payload.page_context,
                "updated_at":   now,
            },
            on_conflict="user_id",
        ).execute()
    except Exception as e:
        log.error("GPS upsert failed", error=str(e), user_id=user.user_id)
        raise HTTPException(status_code=500, detail=db_error_response(e)["error"])

    response = {
        "success":      True,
        "user_id":      user.user_id,
        "latitude":     payload.latitude,
        "longitude":    payload.longitude,
        "page_context": payload.page_context,
        "updated_at":   now,
    }
    if not india_valid:
        response["warning"] = "Coordinates are outside India's bounding box — verify location."

    return response


@app.get("/api/gps")
async def list_gps_locations(request: Request):
    """
    Get GPS locations.
    - Admin: returns ALL active users' locations
    - Citizen/responder: returns only their own location

    Query params:
      context  — filter by page_context ('citizen'|'admin'|...)
      stale_minutes — exclude entries older than N minutes (default 10)
    """
    user   = require_auth(request)
    params = dict(request.query_params)
    stale  = int(params.get("stale_minutes", 10))
    context_filter = params.get("context", "")

    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale)).isoformat()

    sb = get_client()
    try:
        if user.is_admin() or user.is_responder():
            # Full picture for dispatchers
            q = (
                sb.table("gps_locations")
                .select("user_id, latitude, longitude, page_context, updated_at")
                .gte("updated_at", cutoff)
                .order("updated_at", desc=True)
            )
            if context_filter:
                q = q.eq("page_context", context_filter)
        else:
            # Citizens: only themselves
            q = (
                sb.table("gps_locations")
                .select("user_id, latitude, longitude, page_context, updated_at")
                .eq("user_id", user.user_id)
            )

        result = q.execute()
    except Exception as e:
        log.error("GPS list failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch GPS locations.")

    return {"locations": result.data, "total": len(result.data)}


@app.get("/api/gps/{user_id}")
async def get_user_location(user_id: str, request: Request):
    """
    Get the last known GPS location for a specific user.
    Admin only (used to track team / citizen locations for dispatch).
    """
    auth_user = require_auth(request)
    require_role(auth_user, "admin", "responder")

    sb = get_client()
    try:
        result = (
            sb.table("gps_locations")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch location.")

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail=f"No GPS location found for user {user_id}.",
        )

    return result.data


# ── Vercel handler ─────────────────────────────────────────────
handler = app
