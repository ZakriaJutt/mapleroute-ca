"""Sliding-window counters in process memory for sign-in anti-automation (B2, ASVS 6.3.1, 2.4.1).

One console process keeps its own windows; the per-credential lockout in the database
(``local_credential.failed_count``) holds across processes. No shared cache (R-05).
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta


class SlidingWindow:
    def __init__(self, limit: int, period: timedelta) -> None:
        self.limit = limit
        self.period = period
        self._lock = threading.Lock()
        self._hits: dict[str, deque[datetime]] = {}

    def allow(self, key: str, now: datetime) -> bool:
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.period:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
