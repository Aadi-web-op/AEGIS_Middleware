"""In-memory brute-force protection for the login endpoint."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

MAX_FAILURES = 5          # per (client, email) inside the window
MAX_FAILURES_PER_IP = 20  # per client, any email (credential stuffing)
WINDOW_SECONDS = 15 * 60


class LoginLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._failures: dict[tuple, deque] = defaultdict(deque)
        self._lock = Lock()

    def _recent(self, key: tuple) -> deque:
        q = self._failures[key]
        cutoff = self._clock() - WINDOW_SECONDS
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def retry_after(self, client: str, email: str) -> int:
        """Seconds until another attempt is allowed; 0 when allowed now."""
        with self._lock:
            waits = []
            for key, limit in (((client, email), MAX_FAILURES), ((client,), MAX_FAILURES_PER_IP)):
                q = self._recent(key)
                if len(q) >= limit:
                    waits.append(int(q[0] + WINDOW_SECONDS - self._clock()) + 1)
            return max(waits, default=0)

    def failed(self, client: str, email: str) -> None:
        with self._lock:
            now = self._clock()
            self._failures[(client, email)].append(now)
            self._failures[(client,)].append(now)

    def succeeded(self, client: str, email: str) -> None:
        with self._lock:
            self._failures.pop((client, email), None)
