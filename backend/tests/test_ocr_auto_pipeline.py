"""Provider failure and disagreement must not discard a successful primary."""
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.models import Expense
from app.services.ocr_service import OcrResult, _apply, collect_auto_ocr_extractions


def _providers(monkeypatch, primary, enhancement):
    monkeypatch.setattr(_apply, "get_settings", lambda: SimpleNamespace(
        ocr_auto_run=True, ocr_provider="mock", ocr_fallback_provider="rapidocr",
        ocr_min_confidence=0.95))

    class Provider:
        def __init__(self, result):
            self.result = result

        def extract(self, *_args, **_kwargs):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    monkeypatch.setattr(_apply, "get_ocr_provider", lambda name:
        Provider(primary if name == "mock" else enhancement))


def _expense():
    return Expense(status="pending", category="其他", home_currency_code="CNY", original_currency_code="CNY")


def test_enhancement_timeout_preserves_primary(monkeypatch):
    primary = OcrResult(raw_text="商户：盒马\n实付：18.00", confidence=0.8)
    _providers(monkeypatch, primary, AppError("ocr_timeout", status_code=503))
    results = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert results.extractions[0].result == primary
    assert results.notice == "enhancement_failed"
    assert [attempt.outcome for attempt in results.attempts] == ["succeeded", "failed"]
    assert results.attempts[1].error_code == "ocr_timeout"


@pytest.mark.parametrize("primary", [AppError("ocr_worker_crashed", status_code=503), OcrResult("", None)])
def test_no_successful_result_does_not_claim_partial_success(monkeypatch, primary):
    _providers(monkeypatch, primary, AppError("ocr_timeout", status_code=503))
    with pytest.raises(AppError):
        collect_auto_ocr_extractions(_expense(), raise_on_failure=True)


@pytest.mark.parametrize("confidence", [0.1, 0.99])
def test_conflicting_enhancement_is_preserved_but_cannot_replace_primary(monkeypatch, confidence):
    primary = OcrResult(raw_text="商户：盒马\n实付：18.00", confidence=0.8)
    fallback = OcrResult(raw_text="商户：盒马\n实付：78.00", confidence=confidence)
    _providers(monkeypatch, primary, fallback)
    run = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert run.notice == "provider_conflict"
    assert [item.result for item in run.extractions] == [fallback, primary]
    assert [item.apply_to_draft for item in run.extractions] == [False, True]


@pytest.mark.parametrize("text", ["商户：盒马\n实付：78.00", "退款成功\n退款金额：18.00", "实付：18.00\n实付：78.00"])
def test_empty_primary_can_use_successful_enhancement(monkeypatch, text):
    primary = OcrResult("", None)
    fallback = OcrResult(raw_text=text, confidence=0.1)
    _providers(monkeypatch, primary, fallback)
    run = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert run.notice is None
    assert run.extractions[-1].result == fallback
    assert run.extractions[-1].apply_to_draft


def test_empty_enhancement_is_not_a_conflicting_prediction(monkeypatch):
    primary = OcrResult(raw_text="退款成功\n退款金额：18.00", confidence=0.8)
    _providers(monkeypatch, primary, OcrResult("", None))
    run = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert run.notice is None
    assert run.extractions[-1].result == primary
    assert run.attempts[-1].outcome == "no_result"


def test_enhancement_must_preserve_known_fields_and_add_evidence(monkeypatch):
    primary = OcrResult(raw_text="商户：盒马", confidence=0.8)
    fallback = OcrResult(raw_text="商户：盒马\n实付：78.00", confidence=0.1)
    _providers(monkeypatch, primary, fallback)
    run = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert run.notice is None
    assert run.extractions[-1].result == fallback


def test_missing_enhancement_field_cannot_drop_primary_evidence(monkeypatch):
    primary = OcrResult(raw_text="商户：盒马\n实付：18.00", confidence=0.8)
    fallback = OcrResult(raw_text="实付：18.00", confidence=0.99)
    _providers(monkeypatch, primary, fallback)
    run = collect_auto_ocr_extractions(_expense(), raise_on_failure=True)
    assert run.notice is None
    assert run.extractions[-1].result == primary
