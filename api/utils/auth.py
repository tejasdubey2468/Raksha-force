"""
RAKSHA-FORCE — JWT Auth Utilities
──────────────────────────────────
Validates Supabase-issued JWTs (RS256 / HS256) and extracts
the user_id + role from the token payload.

Environment variable required:
    SUPABASE_JWT_SECRET   = your-supabase-project-jwt-secret
    (Found in: Supabase Dashboard → Project Settings → API → JWT Secret)

Usage:
    from api.utils.auth import require_auth, require_role

    user = require_auth(request)           # raises HTTPException if invalid
    require_role(user, "admin")            # raises HTTPException if wrong role
"""

import os
import time
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

# ── Config ─────────────────────────────────────────────────────

JWT_SECRET   = os.environ.get("SUPABASE_JWT_SECRET", "")
JWT_AUDIENCE = "authenticated"  # Supabase always issues with this audience


# ── Models ─────────────────────────────────────────────────────

class AuthUser:
    """Authenticated user extracted from a verified JWT."""

    def __init__(self, payload: dict):
        self.user_id: str         = payload.get("sub", "")
        self.email:   str         = payload.get("email", "")
        self.role:    str         = payload.get("user_metadata", {}).get("role", "citizen")
        self.exp:     int         = payload.get("exp", 0)
        self._raw:    dict        = payload

    def is_admin(self)     -> bool: return self.role == "admin"
    def is_citizen(self)   -> bool: return self.role in ("citizen", "")
    def is_responder(self) -> bool: return self.role == "responder"


# ── Core verification ──────────────────────────────────────────

def verify_token(token: str) -> dict:
    """
    Decode and verify a Supabase JWT.

    Args:
        token: Raw JWT string (without 'Bearer ' prefix)

    Returns:
        Decoded payload dict

    Raises:
        HTTPException 401: Token is missing, expired, or tampered with
    """
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server auth configuration error (missing JWT secret).",
        )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=JWT_AUDIENCE,
            options={"require": ["sub", "exp", "aud"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token audience mismatch.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_token(request: Request) -> Optional[str]:
    """
    Pull the Bearer token from the Authorization header.

    Returns:
        Token string, or None if header is absent/malformed.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return None


# ── Dependency helpers ─────────────────────────────────────────

def require_auth(request: Request) -> AuthUser:
    """
    FastAPI dependency — validates JWT and returns AuthUser.

    Raises:
        HTTPException 401: If token is missing or invalid

    Example:
        @app.post("/api/sos")
        async def create_sos(request: Request):
            user = require_auth(request)
            ...
    """
    token = extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or malformed. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(token)
    return AuthUser(payload)


def require_role(user: AuthUser, *allowed_roles: str) -> AuthUser:
    """
    Assert that the authenticated user holds one of the allowed roles.

    Args:
        user:          AuthUser from require_auth()
        allowed_roles: One or more role strings (e.g. "admin", "responder")

    Raises:
        HTTPException 403: If user's role is not in allowed_roles

    Example:
        user = require_auth(request)
        require_role(user, "admin")
    """
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Required role(s): {', '.join(allowed_roles)}. "
                   f"Your role: {user.role}",
        )
    return user


def optional_auth(request: Request) -> Optional[AuthUser]:
    """
    Like require_auth but returns None instead of raising for unauthenticated requests.
    Useful for public-read endpoints that have extra features when logged in.
    """
    token = extract_token(request)
    if not token:
        return None
    try:
        payload = verify_token(token)
        return AuthUser(payload)
    except HTTPException:
        return None
