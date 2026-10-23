"""Single-flight background telemetry; callbacks are dispatched to the UI."""
from __future__ import annotations

import threading
from typing import Callable, Generic, TypeVar

Snapshot = TypeVar("Snapshot")


class SnapshotPoller(Generic[Snapshot]):
    def __init__(self, reader: Callable[[], Snapshot], dispatch: Callable) -> None:
        self.reader = reader
        self.dispatch = dispatch
        self._lock = threading.Lock()
        self._busy = False
        self._closed = False

    def request(self, success: Callable, failure: Callable) -> bool:
        with self._lock:
            if self._busy or self._closed:
                return False
            self._busy = True

        def worker() -> None:
            try:
                value, error = self.reader(), None
            except Exception as exc:
                value, error = None, str(exc)

            def deliver() -> bool:
                with self._lock:
                    self._busy = False
                    closed = self._closed
                if not closed:
                    if error is None:
                        success(value)
                    else:
                        failure(error)
                return False

            self.dispatch(deliver)

        threading.Thread(target=worker, name="awcc-telemetry", daemon=True).start()
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
