"""Load protection: a concurrency gate for inference and a rate limiter for the paid extra analysis."""
import asyncio
import time
from collections import deque


class Busy(Exception):
    """Too many requests are running and waiting."""


class ConcurrencyGate:
    """At most `max_running` bodies run at once; up to `max_waiting` more wait; the rest are refused at once
    (a quick 503 beats a request that hangs for minutes)."""

    def __init__(self, max_running: int, max_waiting: int):
        self.max_running, self.max_waiting = max(1, max_running), max(0, max_waiting)
        self._sem = asyncio.Semaphore(self.max_running)
        self.running = 0
        self.waiting = 0

    async def __aenter__(self):
        if self.running >= self.max_running:
            if self.waiting >= self.max_waiting:
                raise Busy()
            self.waiting += 1
            try:
                await self._sem.acquire()
            finally:
                self.waiting -= 1
        else:
            await self._sem.acquire()
        self.running += 1
        return self

    async def __aexit__(self, *exc):
        self.running -= 1
        self._sem.release()


class RateLimiter:
    """Sliding window over the whole service: `max_events` per `window` seconds."""

    def __init__(self, max_events: int, window: float = 60.0, clock=time.monotonic):
        self.max_events, self.window, self.clock = max_events, window, clock
        self._events = deque()

    def allow(self) -> bool:
        now = self.clock()
        while self._events and now - self._events[0] >= self.window:
            self._events.popleft()
        if len(self._events) >= self.max_events:
            return False
        self._events.append(now)
        return True
