"""All real recognition entry points spend the same process-local request budget."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config
from app.errors import AppError
from app.services import ocr_worker_client
from app.services import recognition_resource_admission as admission
from app.services import windows_recognition_resources as resources
from app.services.local_llm_vision import local_llm_slot


@pytest.fixture(autouse=True)
def isolated_budget(monkeypatch):
    budget = admission.RecognitionBudget()
    monkeypatch.setattr(admission, "_BUDGET", budget)
    yield budget
    budget.close()


@pytest.mark.parametrize("region", [None, [0, 0, 10, 10]])
def test_local_vision_request_blocks_native_full_and_region_at_the_same_limit(monkeypatch, region):
    settings = replace(config.get_settings(), local_llm_max_concurrent=1)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(ocr_worker_client._CLIENT, "timeout_seconds", 0)
    calls = []
    monkeypatch.setattr(ocr_worker_client._CLIENT, "recognize", lambda *args, **kwargs: calls.append(kwargs) or {})
    with local_llm_slot(max_concurrent=1, queue_timeout_seconds=0):
        with pytest.raises(AppError) as caught:
            if region is None:
                ocr_worker_client.recognize_snapshot(Path("unused.png"), "a" * 64)
            else:
                ocr_worker_client.recognize_region_snapshot(Path("unused.png"), "a" * 64, region)
        assert caught.value.error == "rate_limited" and calls == []
    ocr_worker_client.recognize_snapshot(Path("unused.png"), "a" * 64)
    assert calls == [{}]


def test_request_failure_releases_shared_capacity_but_native_calls_stay_single():
    with admission.recognition_slot("rapidocr", limit=2, timeout=0):
        with pytest.raises(AppError), admission.recognition_slot("rapidocr", limit=2, timeout=0):
            pass
        with pytest.raises(ValueError), local_llm_slot(max_concurrent=2, queue_timeout_seconds=0):
            raise ValueError("request failed")
        with local_llm_slot(max_concurrent=2, queue_timeout_seconds=0):
            pass


@pytest.mark.parametrize("first", ["signal", "physical", "commit"])
def test_memory_pressure_waits_for_high_signal_and_full_worker_reserve(monkeypatch, first):
    clock = [0.0]
    monkeypatch.setattr(resources, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    observer = resources.PressureObserver()
    plenty = resources.WORKER_MEMORY_BYTES * 3
    reading = [resources.ResourceReading(first == "signal", False,
        1 if first == "physical" else plenty, 1 if first == "commit" else plenty, 0, 10)]
    monkeypatch.setattr(observer.reader, "read", lambda: reading[0])
    assert observer.sample().memory
    clock[0] += 2
    reading[0] = resources.ResourceReading(False, False, plenty, plenty, 10, 20)
    assert observer.sample().memory, "neutral memory must not repeatedly restart a cold model"
    clock[0] += 2
    reading[0] = resources.ResourceReading(False, True, plenty, plenty, 20, 30)
    assert not observer.sample().memory
    observer.close()


def test_cpu_saturation_and_recovery_require_two_complete_sample_windows(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(resources, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    observer = resources.PressureObserver()
    reading = [resources.ResourceReading(False, True, 2**30, 2**30, 0, 10)]
    monkeypatch.setattr(observer.reader, "read", lambda: reading[0])
    assert not observer.sample().cpu
    for instant, idle, expected in ((2, 0, False), (4, 0, True), (6, 10, True), (8, 20, False)):
        clock[0] = instant
        reading[0] = resources.ResourceReading(False, True, 2**30, 2**30, idle, 10 + instant * 10)
        assert observer.sample().cpu is expected
    observer.close()


def test_probe_failure_defers_without_inventing_capacity_or_starting_native(isolated_budget, monkeypatch):
    def unavailable():
        raise OSError("probe unavailable")

    monkeypatch.setattr(isolated_budget._observer, "sample", unavailable)
    assert admission.defer_ocr_dispatch("expense_ocr_retry")
    with pytest.raises(AppError), admission.recognition_slot("rapidocr", limit=2, timeout=0):
        pass
    monkeypatch.setattr(isolated_budget._observer, "sample", lambda: resources.RecognitionPressure())
    assert not admission.defer_ocr_dispatch("expense_ocr_retry")


def test_stopping_does_not_reopen_closed_resource_handles(isolated_budget, monkeypatch):
    reads = []
    monkeypatch.setattr(isolated_budget._observer, "sample", lambda: reads.append(1) or resources.RecognitionPressure())
    isolated_budget.close()
    assert admission.defer_ocr_dispatch("expense_ocr_retry")
    with pytest.raises(AppError), admission.recognition_slot("rapidocr", limit=2, timeout=0):
        pass
    assert reads == []
    isolated_budget.start()
    with admission.recognition_slot("rapidocr", limit=2, timeout=0):
        pass
