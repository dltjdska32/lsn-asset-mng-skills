"""Bounded provider calls with process-local, capability-scoped circuit health."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from queue import Queue, Empty
from threading import Thread
from time import monotonic


@dataclass(frozen=True, slots=True)
class ProviderExecutionPolicy:
    attempt_timeout_seconds: float = 15.0
    total_timeout_seconds: float = 35.0
    max_retries: int = 1
    cooldown_seconds: float = 60.0

    def __post_init__(self):
        for value in (self.attempt_timeout_seconds, self.total_timeout_seconds, self.cooldown_seconds):
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError("provider time budgets must be finite and positive")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be an integer between 0 and 3")


class BoundedProviderCalls:
    """A timed-out daemon cannot publish a late result or create repeated workers.

    Python cannot forcibly cancel a transport. At most one worker for each key
    remains in flight; later calls skip it until it exits. HTTP transports still
    receive their normal socket timeout and keep certificate validation intact.
    """
    def __init__(self):
        self._active = {}
        self._unhealthy_until = {}

    def blocked_reason(self, key):
        worker = self._active.get(key)
        if worker is not None:
            if worker.is_alive():
                return "previous provider attempt still in flight"
            self._active.pop(key, None)
        if monotonic() < self._unhealthy_until.get(key, 0):
            return "provider health cooldown"
        return None

    def mark_failed(self, key, cooldown):
        self._unhealthy_until[key] = monotonic() + cooldown

    def mark_healthy(self, key):
        self._unhealthy_until.pop(key, None)

    def call(self, key, operation, timeout):
        queue = Queue(maxsize=1)
        def run():
            try:
                queue.put((True, operation()))
            except Exception as exc:
                queue.put((False, exc))
        worker = Thread(target=run, daemon=True, name="provider-call")
        self._active[key] = worker
        worker.start()
        try:
            success, value = queue.get(timeout=timeout)
        except Empty:
            raise TimeoutError("provider attempt exceeded time budget") from None
        self._active.pop(key, None)
        if not success:
            raise value
        return value
