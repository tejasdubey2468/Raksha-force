"""
RAKSHA-FORCE — In-Memory Rate Limiter
──────────────────────────────────────
Simple sliding-window rate limiter for Vercel serverless functions.
Note: Since each serverless invocation is isolated, this resets per
cold start. For production, use Supabase Edge Functions or Redis (Upstash).

Usage:
    from api.utils.rate_limit import RateLimiter

    sos_limiter = RateLimiter(max_calls=5, window_seconds=60)

    # In your handler:
    allowed, retry_after = sos_limiter.check(ip_address)
    if not allowed:
        raise HTTPException(429, f"Rate limit exceeded. Retry after {retry_after}s.")
"""

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    """
    Sliding window rate limiter keyed by identifier (IP, user_id, etc.).

    Args:
        max_calls:       Maximum number of calls allowed per window
        window_seconds:  Duration of the sliding window in seconds
    """

    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls      = max_calls
        self.window_seconds = window_seconds
        self._timestamps: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def check(self, identifier: str) -> tuple[bool, int]:
        """
        Check if a request is within the rate limit.

        Args:
            identifier: Unique key (IP address, user_id, etc.)

        Returns:
            (allowed: bool, retry_after_seconds: int)
            retry_after is 0 when allowed.
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            q = self._timestamps[identifier]

            # Evict expired timestamps
            while q and q[0] < cutoff:
                q.popleft()

            if len(q) >= self.max_calls:
                # How long until the oldest call expires
                retry_after = int(q[0] - cutoff) + 1
                return False, retry_after

            q.append(now)
            return True, 0

    def reset(self, identifier: str) -> None:
        """Clear all recorded calls for an identifier."""
        with self._lock:
            self._timestamps.pop(identifier, None)


# ── Shared limiters (module-level singletons) ──────────────────

# SOS: max 5 per minute per IP (emergency, but prevent spam)
sos_limiter = RateLimiter(max_calls=5, window_seconds=60)

# Incidents: max 20 per minute per user
incident_limiter = RateLimiter(max_calls=20, window_seconds=60)

# Dispatch: max 30 per minute per admin (higher, admin is trusted)
dispatch_limiter = RateLimiter(max_calls=30, window_seconds=60)

# GPS updates: max 60 per minute per user (every second)
gps_limiter = RateLimiter(max_calls=60, window_seconds=60)

# Volunteers: max 3 registrations per hour per IP
volunteer_limiter = RateLimiter(max_calls=3, window_seconds=3600)
