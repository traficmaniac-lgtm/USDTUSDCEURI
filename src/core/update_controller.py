"""Shared update controller to run exchange jobs safely."""

from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Callable, Generic, TypeVar

from PySide6.QtCore import QObject, Signal

MAX_EXCHANGE_WORKERS = 4
MAX_HTTP_CONCURRENCY = 4

_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_EXCHANGE_WORKERS)
_HTTP_SEMAPHORE = threading.BoundedSemaphore(MAX_HTTP_CONCURRENCY)

T = TypeVar("T")


class UpdateJob(QObject, Generic[T]):
    """Signals for a single update job."""

    started = Signal(int)
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal(int)


class SafeUpdateController(QObject):
    """Submits one-shot jobs with run_id/in-flight protection."""

    def __init__(self) -> None:
        super().__init__()
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    def submit(
        self, key: str, run_id: int, task: Callable[[], T]
    ) -> UpdateJob[T] | None:
        with self._lock:
            if key in self._in_flight:
                return None
            self._in_flight.add(key)
        job: UpdateJob[T] = UpdateJob()
        job.started.emit(run_id)

        future = _EXECUTOR.submit(task)

        def _done(fut) -> None:
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001 - surface job failures
                job.failed.emit(run_id, str(exc))
            else:
                job.succeeded.emit(run_id, result)
            finally:
                with self._lock:
                    self._in_flight.discard(key)
                job.finished.emit(run_id)

        future.add_done_callback(_done)
        return job

    def clear_key(self, key: str) -> None:
        with self._lock:
            self._in_flight.discard(key)


_controller: SafeUpdateController | None = None


def get_update_controller() -> SafeUpdateController:
    global _controller  # noqa: PLW0603 - module-level singleton
    if _controller is None:
        _controller = SafeUpdateController()
    return _controller


@contextmanager
def http_slot():
    _HTTP_SEMAPHORE.acquire()
    try:
        yield
    finally:
        _HTTP_SEMAPHORE.release()
