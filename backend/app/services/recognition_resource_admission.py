"""One local recognition request budget across native OCR and local vision callers."""

import atexit
import logging
import threading
import time
from contextlib import contextmanager

from app import config
from app.error_reporting import report_error
from app.errors import AppError
from app.services.windows_recognition_resources import SAMPLE_SECONDS, PressureObserver, RecognitionPressure

logger = logging.getLogger(__name__)


class RecognitionBudget:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active = {"rapidocr": 0, "local_llm": 0}
        self._observer = PressureObserver()
        self._stopping = False
        self._reported_probe_error = False

    def _pressure(self) -> RecognitionPressure:
        try:
            pressure = self._observer.sample()
            self._reported_probe_error = False
            return pressure
        except OSError as error:
            if not self._reported_probe_error:
                report_error(logger, "recognition resource probe unavailable", error=error)
                self._reported_probe_error = True
            return RecognitionPressure(memory=True, cpu=True)

    def deferred(self, *, background: bool) -> bool:
        with self._condition:
            if self._stopping:
                return True
            pressure = self._pressure()
            limit = max(1, config.get_settings().local_llm_max_concurrent)
            return (sum(self._active.values()) >= limit
                or pressure.memory or background and pressure.cpu)

    def acquire(self, kind: str, *, limit: int, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                if self._stopping:
                    raise AppError("rate_limited", status_code=429)
                pressure = self._pressure()
                native_busy = kind == "rapidocr" and self._active["rapidocr"] > 0
                if not pressure.memory and not native_busy and sum(self._active.values()) < max(1, limit):
                    self._active[kind] += 1
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AppError("rate_limited", "本机识别暂时繁忙，原输入仍保留，可稍后再试或手动填写。", status_code=429)
                self._condition.wait(min(remaining, SAMPLE_SECONDS))

    def release(self, kind: str) -> None:
        with self._condition:
            self._active[kind] -= 1
            self._condition.notify_all()

    def start(self) -> None:
        with self._condition:
            if any(self._active.values()):
                raise RuntimeError("previous recognition requests have not returned")
            self._observer.close()
            self._observer = PressureObserver()
            self._stopping = False

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            self._observer.close()


_BUDGET = RecognitionBudget()
atexit.register(_BUDGET.close)


@contextmanager
def recognition_slot(kind: str, *, limit: int, timeout: float):
    _BUDGET.acquire(kind, limit=limit, timeout=timeout)
    try:
        yield
    finally:
        # This releases the software request. An external model may still be
        # computing after an HTTP timeout; its process remains externally owned.
        _BUDGET.release(kind)


def defer_ocr_dispatch(task_type: str) -> bool:
    return _BUDGET.deferred(background=task_type == "expense_enrichment")


def defer_optional_enhancement() -> bool:
    return _BUDGET.deferred(background=True)


def start_recognition_admission() -> None:
    _BUDGET.start()


def shutdown_recognition_admission() -> None:
    _BUDGET.close()
