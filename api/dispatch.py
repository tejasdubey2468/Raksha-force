"""
RAKSHA-FORCE — Smart Dispatch System
──────────────────────────────────────
POST /api/dispatch                → Auto-dispatch nearest suitable team
GET  /api/dispatch/{incident_id}  → Get dispatch status for an incident
DELETE /api/dispatch/{incident_id}→ Un-assign team (re-open incident)

Algorithm:
  1. Validate incident exists and is pending/unassigned
  2. Fetch all available teams
  3. Filter by matching type (fire→fire, medical→medical, etc.)
  4. Calculate Haversine distance from each team to incident
  5. Sort by composite score (distance + type match + load factor)
  6. Insert into assignments table
  7. Mark team status = 'busy', incident status = 'assigned'
  8. Return dispatch details including ETA

─── Example: Dispatch ────────────────────────────────────────────────────────

POST /api/dispatch
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{
  "incident_id": "f3a2b1c4-...",
  "force_team_id": null        ← optional: skip auto-select, use this team
}

→ 200 OK
{
  "success": true,
  "incident_id": "f3a2b1c4-...",
  "assigned_team": {
    "id":   "team-uuid",
    "name": "Bravo Ambulance",
    "type": "medical"
  },
  "distance_km": 2.3,
  "eta_minutes": 5,
  "assignment_id": "assign-uuid"
}
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.utils.auth import require_auth, require_role
from api.utils.db import db_error_response, get_client
from api.utils.geo import haversine_distance, estimate_eta_minutes
from api.utils.logger import get_logger
from api.utils.rate_limit import dispatch_limiter

# ── App ────────────────────────────────────────────────────────

app = FastAPI(title="RAKSHA-FORCE Dispatch API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

log = get_logger("dispatch")

# ── Type mapping (emergency_type → preferred team.type) ────────

EMERGENCY_TO_TEAM_TYPE = {
    "fire":         ["fire",    "ndrf"],
    "medical":      ["medical", "fire"],
    "ambulance":    ["medical"],
    "fire_brigade": ["fire"],
    "accident":     ["medical", "fire", "police"],
    "flood":        ["ndrf",    "fire"],
    "police":       ["police"],
    "women":        ["police"],
    "child":        ["police",  "medical"],
    "missing":      ["police"],
    "other":        ["police",  "medical", "fire", "ndrf"],
}


# ── Schemas ────────────────────────────────────────────────────

class DispatchRequest(BaseModel):
    incident_id:   str        = Field(..., description="UUID of the incident to dispatch")
    force_team_id: str | None = Field(None, description="Bypass auto-select; assign this team directly")
    notes:         str        = Field("", max_length=500, description="Optional dispatch notes")


# ── Handlers ───────────────────────────────────────────────────

@app.post("/api/dispatch")
async def dispatch_team(request: Request):
    """
    Smart dispatch: find the best available team for an incident.
    Admin only. Rate limited.
    """
    user = require_auth(request)
    require_role(user, "admin")

    client_ip = request.client.host or "unknown"
    allowed, retry_after = dispatch_limiter.check(user.user_id or client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Wait {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    try:
        payload = DispatchRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    sb = get_client()

    # ── Step 1: Load incident ──────────────────────────────────
    try:
        inc_result = (
            sb.table("incident_reports")
            .select("id, emergency_type, status, latitude, longitude, priority")
            .eq("id", payload.incident_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Incident not found.")

    incident = inc_result.data
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if incident["status"] == "resolved":
        raise HTTPException(status_code=409, detail="Cannot dispatch to a resolved incident.")

    # Check if already assigned
    existing = (
        sb.table("assignments")
        .select("id, team_id")
        .eq("incident_id", payload.incident_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409,
            detail="Incident already has an assigned team. Un-assign first.",
        )

    # ── Step 2: Select team ────────────────────────────────────
    if payload.force_team_id:
        team = _load_team(sb, payload.force_team_id)
    else:
        team = _find_best_team(sb, incident)

    if not team:
        raise HTTPException(
            status_code=503,
            detail="No available teams found. All units are currently busy.",
        )

    # ── Step 3: Calculate distance & ETA ──────────────────────
    distance_km = haversine_distance(
        incident["latitude"], incident["longitude"],
        team["latitude"],    team["longitude"],
    )
    eta = estimate_eta_minutes(distance_km, team["type"])

    # ── Step 4: Insert assignment ──────────────────────────────
    try:
        assign_result = sb.table("assignments").insert({
            "incident_id": payload.incident_id,
            "team_id":     team["id"],
            "eta_minutes": eta,
            "notes":       payload.notes or f"Auto-dispatched. Distance: {distance_km:.1f}km",
        }).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=db_error_response(e)["error"])

    assignment = assign_result.data[0] if assign_result.data else {}

    # ── Step 5: Update team → busy & incident → assigned ──────
    try:
        sb.table("teams").update({
            "status":       "busy",
            "current_load": team.get("current_load", 0) + 1,
        }).eq("id", team["id"]).execute()

        sb.table("incident_reports").update({
            "status":         "assigned",
            "assigned_team_id": team["id"],
            "updated_at":     _now_iso(),
        }).eq("id", payload.incident_id).execute()
    except Exception as e:
        log.error("Post-assignment update failed", error=str(e))
        # Assignment was created — don't roll back, just warn

    log.info(
        "Team dispatched",
        incident_id=payload.incident_id,
        team=team["name"],
        distance_km=round(distance_km, 2),
        eta=eta,
        admin=user.user_id,
    )

    return {
        "success":       True,
        "incident_id":   payload.incident_id,
        "assigned_team": {
            "id":   team["id"],
            "name": team["name"],
            "type": team["type"],
        },
        "distance_km":   round(distance_km, 2),
        "eta_minutes":   eta,
        "assignment_id": assignment.get("id"),
    }


@app.get("/api/dispatch/{incident_id}")
async def get_dispatch_status(incident_id: str, request: Request):
    """
    Get the dispatch/assignment status for a specific incident.
    Accessible to admins; citizens see their own only.
    """
    user = require_auth(request)
    sb   = get_client()

    try:
        inc = (
            sb.table("incident_reports")
            .select("id, status, emergency_type, user_id")
            .eq("id", incident_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Incident not found.")

    if user.is_citizen() and inc.data.get("user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    try:
        result = (
            sb.table("assignments")
            .select("*, teams(id, name, type, status, latitude, longitude)")
            .eq("incident_id", incident_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch dispatch status.")

    if not result.data:
        return {
            "incident_id": incident_id,
            "status":      inc.data.get("status", "pending"),
            "assignment":  None,
            "message":     "No team assigned yet.",
        }

    return {
        "incident_id": incident_id,
        "status":      inc.data.get("status"),
        "assignment":  result.data,
    }


@app.delete("/api/dispatch/{incident_id}", status_code=status.HTTP_200_OK)
async def unassign_team(incident_id: str, request: Request):
    """
    Un-assign a team from an incident (Admin only).
    - Deletes the assignment record
    - Resets team → available
    - Resets incident → pending
    """
    user = require_auth(request)
    require_role(user, "admin")

    sb = get_client()

    # Find the assignment
    try:
        assign = (
            sb.table("assignments")
            .select("id, team_id")
            .eq("incident_id", incident_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="No assignment found for this incident.")

    team_id     = assign.data["team_id"]
    assignment_id = assign.data["id"]

    # Delete assignment
    sb.table("assignments").delete().eq("id", assignment_id).execute()

    # Reset team → available
    team = _load_team(sb, team_id)
    if team:
        sb.table("teams").update({
            "status":       "available",
            "current_load": max(0, team.get("current_load", 1) - 1),
        }).eq("id", team_id).execute()

    # Reset incident → pending
    sb.table("incident_reports").update({
        "status":           "pending",
        "assigned_team_id": None,
        "updated_at":       _now_iso(),
    }).eq("id", incident_id).execute()

    log.info("Team unassigned", incident_id=incident_id, team_id=team_id, admin=user.user_id)
    return {"success": True, "incident_id": incident_id, "message": "Team un-assigned."}


# ── Internal helpers ───────────────────────────────────────────

def _find_best_team(sb, incident: dict) -> dict | None:
    """
    Find the best available team for an incident using:
      1. Type matching (preferred types get priority)
      2. Haversine distance
      3. Load factor (prefer teams with fewer current assignments)

    Returns the best team dict, or None if no teams available.
    """
    emergency_type  = incident.get("emergency_type", "other")
    preferred_types = EMERGENCY_TO_TEAM_TYPE.get(emergency_type, ["police"])

    # Fetch all available teams (with GPS)
    try:
        result = (
            sb.table("teams")
            .select("*")
            .eq("status", "available")
            .execute()
        )
        teams = [
            t for t in (result.data or [])
            if t.get("latitude") and t.get("longitude")
        ]
    except Exception as e:
        log.error("Team fetch failed", error=str(e))
        return None

    if not teams:
        return None

    inc_lat = incident["latitude"]
    inc_lng = incident["longitude"]

    def score(team: dict) -> float:
        # Distance in km
        dist = haversine_distance(inc_lat, inc_lng, team["latitude"], team["longitude"])

        # Type penalty: 0 for best match, increases for lower priority
        try:
            type_idx = preferred_types.index(team["type"])
            type_penalty = type_idx * 3.0  # km equivalent
        except ValueError:
            type_penalty = 10.0  # wrong type, but still usable

        # Load factor: busier teams score worse
        load = team.get("current_load", 0)
        cap  = team.get("capacity", 5) or 5
        load_penalty = (load / cap) * 2.0  # up to 2km penalty at full load

        return dist + type_penalty + load_penalty

    best = min(teams, key=score)
    return best


def _load_team(sb, team_id: str) -> dict | None:
    """Load a specific team by ID."""
    try:
        result = sb.table("teams").select("*").eq("id", team_id).single().execute()
        return result.data
    except Exception:
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Vercel handler ─────────────────────────────────────────────
handler = app
