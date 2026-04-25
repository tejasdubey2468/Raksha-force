"""
RAKSHA-FORCE — SOS Alert API
─────────────────────────────
POST /api/sos   → Create an SOS alert (authenticated or anonymous with token)
GET  /api/sos   → List SOS alerts (admin only)

Table: sos_alerts
  id, user_id, type, description, latitude, longitude, status, created_at

─── Example Requests ──────────────────────────────────────────────────────────

POST /api/sos
Authorization: Bearer <supabase-jwt>
Content-Type: application/json

{
  "type": "medical",
  "description": "Person unconscious on road, bleeding from head",
  "latitude": 18.5204,
  "longitude": 73.8567
}

→ 201 Created
{
  "success": true,
  "alert_id": "f3a2b1c4-...",
  "message": "SOS alert created. Help is being dispatched.",
  "estimated_response_minutes": 8
}

─── GET /api/sos (admin) ──────────────────────────────────────────────────────

→ 200 OK
{
  "alerts": [ { "id": "...", "type": "medical", "status": "active", ... } ],
  "total": 12
}
"""

import json
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.utils.auth import optional_auth, require_auth, require_role
from api.utils.db import db_error_response, get_client
from api.utils.geo import validate_coordinates
from api.utils.logger import get_logger
from api.utils.rate_limit import sos_limiter

# ── App setup ──────────────────────────────────────────────────

app = FastAPI(title="RAKSHA-FORCE SOS API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Tighten in production to your domain
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

log = get_logger("sos")

# ── Schemas ────────────────────────────────────────────────────

VALID_SOS_TYPES = {
    "medical", "fire", "police", "flood", "accident",
    "women_safety", "child", "missing", "other",
}


class SOSCreateRequest(BaseModel):
    type:        str   = Field(..., description="Emergency type")
    description: str   = Field("", max_length=1000)
    latitude:    float = Field(..., ge=-90,  le=90)
    longitude:   float = Field(..., ge=-180, le=180)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_SOS_TYPES:
            raise ValueError(
                f"Invalid SOS type '{v}'. Must be one of: {', '.join(sorted(VALID_SOS_TYPES))}"
            )
        return v

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str) -> str:
        return v.strip()


# ── Handlers ───────────────────────────────────────────────────

@app.post("/api/sos", status_code=status.HTTP_201_CREATED)
async def create_sos(request: Request):
    """
    Create an SOS alert.
    - Auth is OPTIONAL: anonymous users can also trigger SOS (life-or-death scenario)
    - Rate limited: max 5 SOS per minute per IP
    - Validates GPS coordinates
    - Inserts into sos_alerts table
    - Attempts to auto-dispatch nearest medical/police team
    """
    # Rate limiting by IP
    client_ip = request.client.host or "unknown"
    allowed, retry_after = sos_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many SOS requests. Please wait {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # Parse body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = SOSCreateRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Optional auth (get user_id if available)
    user = optional_auth(request)
    user_id = user.user_id if user else None

    sb = get_client()

    try:
        result = sb.table("sos_alerts").insert({
            "user_id":     user_id,
            "type":        payload.type,
            "description": payload.description,
            "latitude":    payload.latitude,
            "longitude":   payload.longitude,
            "status":      "active",
        }).execute()
    except Exception as e:
        log.error("SOS insert failed", error=str(e), user_id=user_id)
        err = db_error_response(e)
        raise HTTPException(status_code=500, detail=err["error"])

    alert = result.data[0] if result.data else {}
    alert_id = alert.get("id", "unknown")

    log.info(
        "SOS created",
        alert_id=alert_id,
        type=payload.type,
        lat=payload.latitude,
        lng=payload.longitude,
        user_id=user_id,
    )

    # Trigger auto-dispatch asynchronously (fire-and-forget via Supabase)
    _try_auto_dispatch(sb, alert_id, payload)

    return {
        "success":                     True,
        "alert_id":                    alert_id,
        "message":                     "SOS alert received. Emergency services are being notified.",
        "emergency_numbers":           _emergency_numbers(payload.type),
        "estimated_response_minutes":  8,  # Will be refined by dispatch engine
    }


@app.get("/api/sos")
async def list_sos_alerts(request: Request):
    """
    List SOS alerts — Admin only.
    Query params: status (active|resolved), limit (default 50)
    """
    user = require_auth(request)
    require_role(user, "admin")

    params = dict(request.query_params)
    limit  = min(int(params.get("limit", 50)), 200)
    filter_status = params.get("status", "active")

    sb = get_client()
    try:
        q = (
            sb.table("sos_alerts")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if filter_status:
            q = q.eq("status", filter_status)
        result = q.execute()
    except Exception as e:
        log.error("SOS list failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch SOS alerts.")

    return {"alerts": result.data, "total": len(result.data)}


@app.patch("/api/sos/{alert_id}")
async def update_sos_status(alert_id: str, request: Request):
    """
    Update SOS status — Admin only.
    Body: { "status": "resolved" }
    """
    user = require_auth(request)
    require_role(user, "admin")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    new_status = body.get("status", "").strip()
    if new_status not in ("active", "resolved"):
        raise HTTPException(status_code=422, detail="status must be 'active' or 'resolved'.")

    sb = get_client()
    try:
        sb.table("sos_alerts").update({"status": new_status}).eq("id", alert_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=db_error_response(e)["error"])

    log.info("SOS status updated", alert_id=alert_id, status=new_status, admin=user.user_id)
    return {"success": True, "alert_id": alert_id, "status": new_status}


# ── Helpers ────────────────────────────────────────────────────

def _try_auto_dispatch(sb, alert_id: str, payload: SOSCreateRequest) -> None:
    """
    Best-effort: find nearest available team and create auto-dispatch entry.
    Failures are silently logged — SOS creation must not depend on this.
    """
    try:
        from api.utils.geo import haversine_distance, estimate_eta_minutes

        # Map SOS type → preferred team type
        type_map = {
            "medical": "medical",
            "fire":    "fire",
            "police":  "police",
            "women_safety": "police",
            "child":   "police",
            "flood":   "ndrf",
            "accident": "medical",
            "missing":  "police",
            "other":    "police",
        }
        preferred = type_map.get(payload.type, "police")

        teams_result = sb.table("teams").select("*").eq("status", "available").execute()
        teams = teams_result.data or []

        if not teams:
            return

        # Score: prefer matching type, then closest
        def score(t):
            d = haversine_distance(payload.latitude, payload.longitude, t["latitude"], t["longitude"])
            type_bonus = 0 if t["type"] == preferred else 5  # km penalty for wrong type
            return d + type_bonus

        best = min(teams, key=score)
        eta  = estimate_eta_minutes(
            haversine_distance(payload.latitude, payload.longitude, best["latitude"], best["longitude"]),
            best["type"],
        )

        # Insert auto-dispatch note into sos_alerts (update with assigned team)
        sb.table("sos_alerts").update({
            "description": (
                f"[AUTO-DISPATCH: {best['name']} notified, ETA ~{eta}min] "
            ),
        }).eq("id", alert_id).execute()

        log.info("SOS auto-dispatch", team=best["name"], eta=eta)
    except Exception as e:
        log.error("SOS auto-dispatch failed (non-critical)", error=str(e))


def _emergency_numbers(sos_type: str) -> dict:
    """Return relevant Indian emergency numbers based on SOS type."""
    base = {"all_emergencies": "112"}
    extras = {
        "medical":      {"ambulance": "108"},
        "fire":         {"fire_brigade": "101"},
        "police":       {"police": "100"},
        "women_safety": {"police": "100", "women_helpline": "1091"},
        "child":        {"child_helpline": "1098"},
        "flood":        {"ndrf": "1070"},
        "missing":      {"police": "100"},
    }
    return {**base, **extras.get(sos_type, {})}


# ── Vercel handler ─────────────────────────────────────────────
# Vercel calls the `app` ASGI handler directly.
handler = app
