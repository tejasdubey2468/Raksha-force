"""
RAKSHA-FORCE — Supabase Client (Service-Role)
─────────────────────────────────────────────
Uses the SERVICE_KEY (bypasses RLS) for server-side mutations.
Never expose the service key to the browser.

Environment variables required:
    SUPABASE_URL          = https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  = eyJ...service-role-jwt...

Usage:
    from api.utils.db import get_client

    async with get_client() as sb:
        result = sb.table("incident_reports").select("*").execute()
"""

import os
from contextlib import asynccontextmanager
from functools import lru_cache

from supabase import Client, create_client

# ── Config ────────────────────────────────────────────────────

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Fail fast if not configured
_MISSING_VARS = [
    v for v, val in {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    }.items() if not val
]

# ── Singleton client ───────────────────────────────────────────

_client: Client | None = None


def get_client() -> Client:
    """
    Returns a Supabase service-role client (singleton).
    Thread-safe: supabase-py Client is safe to reuse across requests.

    Raises:
        RuntimeError: If SUPABASE_URL or SUPABASE_SERVICE_KEY are not set.

    Example:
        sb = get_client()
        data = sb.table("teams").select("*").execute()
    """
    global _client

    if _MISSING_VARS:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(_MISSING_VARS)}. "
            "Set them in Vercel → Project → Settings → Environment Variables."
        )

    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    return _client


def db_error_response(exc: Exception) -> dict:
    """
    Standardise a Supabase/postgrest exception into a safe API error dict.
    Never leaks raw SQL errors to the client.
    """
    msg = str(exc)
    # Detect common constraint violations
    if "unique" in msg.lower() or "duplicate" in msg.lower():
        return {"error": "Duplicate entry — record already exists.", "code": "DUPLICATE"}
    if "foreign key" in msg.lower() or "fk_" in msg.lower():
        return {"error": "Referenced resource not found.", "code": "REF_NOT_FOUND"}
    if "not-null" in msg.lower() or "null value" in msg.lower():
        return {"error": "Required field is missing.", "code": "MISSING_FIELD"}
    # Generic fallback — no raw DB internals
    return {"error": "Database operation failed. Please try again.", "code": "DB_ERROR"}
