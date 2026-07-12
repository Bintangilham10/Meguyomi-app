from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class LoginRateLimiter:
    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            failures = self._active_failures(key)
            return len(failures) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            failures = self._active_failures(key)
            failures.append(monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _active_failures(self, key: str) -> deque[float]:
        failures = self._failures[key]
        cutoff = monotonic() - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures
