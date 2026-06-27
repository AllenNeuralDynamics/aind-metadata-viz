"""Per-IP token bucket rate limiter (in-memory, per-process)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    day_count: int = 0
    day_start: float = field(default_factory=time.time)


class RateLimiter:
    """Token-bucket rate limit plus a hard daily cap.

    All limits are per (bucket_key, client_id) pair. Bucket keys let us run
    independent limiters for different endpoints (e.g. "chat" and "mcp").

    ``burst`` is the bucket capacity (max requests allowed instantaneously).
    It defaults to ``per_minute`` for backward compatibility; set it to 1
    to enforce a strict steady rate with no burst allowance.
    """

    def __init__(self, per_minute: int, per_day: int, burst: int | None = None):
        if per_minute <= 0 or per_day <= 0:
            raise ValueError("limits must be positive")
        if burst is not None and burst <= 0:
            raise ValueError("burst must be positive")
        self.per_minute = per_minute
        self.per_day = per_day
        self.burst = burst if burst is not None else per_minute
        self._refill_rate = per_minute / 60.0
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, bucket_key: str, client_id: str) -> tuple[bool, str | None]:
        """Return (allowed, error_message_if_blocked)."""
        now = time.time()
        with self._lock:
            key = (bucket_key, client_id)
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=float(self.burst), last_refill=now)
                self._buckets[key] = b

            if now - b.day_start >= 86400:
                b.day_start = now
                b.day_count = 0

            if b.day_count >= self.per_day:
                return False, (
                    f"Daily limit of {self.per_day} requests exceeded. "
                    "Try again tomorrow."
                )

            elapsed = now - b.last_refill
            b.tokens = min(
                float(self.burst), b.tokens + elapsed * self._refill_rate
            )
            b.last_refill = now

            if b.tokens < 1.0:
                return False, (
                    f"Rate limit exceeded ({self.per_minute}/min). "
                    "Slow down and try again shortly."
                )

            b.tokens -= 1.0
            b.day_count += 1
            return True, None

    def reset(self) -> None:
        """Clear all buckets. Used in tests."""
        with self._lock:
            self._buckets.clear()


def client_ip(headers, fallback: str | None) -> str:
    """Best-effort client IP from request headers."""
    xff = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if xff:
        return xff.split(",")[0].strip()
    return fallback or "unknown"
