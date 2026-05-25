"""v1.2 P0 — OCR facts append-only snapshot table contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from api_contract_helpers import upload_png

from app.database import SessionLocal
from app.models import Expense, OcrFact
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.learning_service import (
    OcrFactDraft,
    ocr_facts_for_expense,
    record_ocr_fact,
)
from app.services.ocr_service import OcrResult, apply_ocr_result
from tests._infra.assets import PNG_BYTES


def _make_expense(tenant_id: str) -> int:
    """Seed a minimal pending expense so the FK on ``ocr_facts.expense_id``
    is satisfiable. Tests that need the OCR-facts table need *an*
    expense to attach to; they don't care about its content."""

    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            source="pytest",
            raw_text="",
            status="pending",
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_record_ocr_fact_persists_full_snapshot(*, identity) -> None:
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        row = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                ocr_model="qwen2.5-vl-7b",
                raw_text="麦当劳 ¥38.50",
                parsed_amount_cents=3850,
                parsed_merchant="麦当劳",
                parsed_category="餐饮",
                parsed_expense_time=datetime(
                    2026, 5, 1, 12, 30, tzinfo=UTC
                ),
                parse_confidence=0.82,
            ),
        )
        db.commit()
        assert row.id is not None
        assert row.ocr_provider == "local_llm"
        assert row.parsed_amount_cents == 3850
        assert row.parsed_category == "餐饮"
        assert row.parse_confidence == pytest.approx(0.82)


def test_record_ocr_fact_allows_partial_results(*, identity) -> None:
    # Real OCR failures yield partial structured guesses — table must
    # accept raw_text alone.
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        row = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="empty",
                raw_text="blurry receipt",
            ),
        )
        db.commit()
        assert row.id is not None
        assert row.parsed_amount_cents is None
        assert row.parsed_merchant is None


def test_facts_returned_newest_first(*, identity) -> None:
    expense_id = _make_expense("owner")
    base = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)
    with SessionLocal() as db:
        for offset_min in (0, 5, 15):
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=expense_id,
                    ocr_provider="local_llm",
                    raw_text=f"text-{offset_min}",
                ),
                now=base + timedelta(minutes=offset_min),
            )
        db.commit()
        facts = ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=expense_id
        )
        assert [f.raw_text for f in facts] == [
            "text-15",
            "text-5",
            "text-0",
        ]


def test_facts_are_tenant_isolated(*, identity) -> None:
    owner_expense_id = _make_expense("owner")
    tester_expense_id = _make_expense("tester_1")
    with SessionLocal() as db:
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=owner_expense_id,
                ocr_provider="local_llm",
                raw_text="owner-text",
            ),
        )
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="tester_1",
                expense_id=tester_expense_id,
                ocr_provider="local_llm",
                raw_text="tester-text",
            ),
        )
        db.commit()

        owner_facts = ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=owner_expense_id
        )
        tester_facts = ocr_facts_for_expense(
            db, tenant_id="tester_1", expense_id=tester_expense_id
        )
        assert len(owner_facts) == 1
        assert len(tester_facts) == 1
        assert owner_facts[0].raw_text == "owner-text"
        assert tester_facts[0].raw_text == "tester-text"


def test_record_ocr_fact_refuses_cross_tenant_expense(*, identity) -> None:
    tester_expense_id = _make_expense("tester_1")
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="another tenant"):
            record_ocr_fact(
                db,
                OcrFactDraft(
                    tenant_id="owner",
                    expense_id=tester_expense_id,
                    ocr_provider="local_llm",
                    raw_text="wrong tenant",
                ),
            )
        db.rollback()


def test_session_bound_apply_requires_fact_pairing(*, identity) -> None:
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        with pytest.raises(RuntimeError, match="apply_ocr_result_and_append_fact"):
            apply_ocr_result(
                expense,
                OcrResult(raw_text="unpaired mirror text\n12.00", confidence=0.8),
            )


def test_apply_with_fact_updates_mirror_and_appends_snapshot(*, identity) -> None:
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        apply_ocr_result_and_append_fact(
            db,
            expense=expense,
            result=OcrResult(
                raw_text="paired mirror text\n交易金额：12.00",
                confidence=0.8,
            ),
            provider_name="manual_text",
        )
        db.commit()

        db.refresh(expense)
        rows = ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=expense_id
        )
        assert expense.raw_text == "paired mirror text\n交易金额：12.00"
        assert len(rows) == 1
        assert rows[0].raw_text == expense.raw_text
        assert rows[0].ocr_provider == "manual_text"


def test_facts_table_is_append_only_no_unique_per_expense(*, identity) -> None:
    # Same expense, repeated runs (manual retry) must produce multiple
    # rows, never an upsert / replace.
    expense_id = _make_expense("owner")
    with SessionLocal() as db:
        first = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="run-1",
            ),
        )
        second = record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="local_llm",
                raw_text="run-2",
            ),
        )
        db.commit()
        assert first.id != second.id
        count = (
            db.query(OcrFact)
            .filter(OcrFact.tenant_id == "owner")
            .filter(OcrFact.expense_id == expense_id)
            .count()
        )
        assert count == 2


def _facts(expense_id: int):
    with SessionLocal() as db:
        return ocr_facts_for_expense(
            db, tenant_id="owner", expense_id=expense_id
        )


def _enable_mock_auto_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ocr_service import _apply as ocr_apply

    settings = replace(
        ocr_apply.get_settings(),
        ocr_auto_run=True,
        ocr_provider="mock",
        ocr_fallback_provider="empty",
    )
    monkeypatch.setattr(ocr_apply, "get_settings", lambda: settings)


def test_upload_link_auto_ocr_writes_fact(
    client, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    _enable_mock_auto_ocr(monkeypatch)

    response = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200, response.json()
    rows = _facts(response.json()["id"])
    assert len(rows) == 1
    assert rows[0].ocr_provider == "mock"
    assert rows[0].parsed_amount_cents == 1851


def test_android_upload_auto_ocr_writes_fact(
    client, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    _enable_mock_auto_ocr(monkeypatch)

    response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.app_headers,
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200, response.json()
    rows = _facts(response.json()["id"])
    assert len(rows) == 1
    assert rows[0].ocr_provider == "mock"
    assert rows[0].parsed_amount_cents == 1851


def test_recognize_text_writes_manual_text_fact(client, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    response = client.post(
        f"/api/expenses/{expense_id}/recognize-text",
        headers=identity.app_headers,
        json={"raw_text": "星巴克\n交易金额：29.00\n交易时间：2026年5月4日 16:23:25"},
    )

    assert response.status_code == 200, response.json()
    rows = _facts(expense_id)
    assert len(rows) == 1
    assert rows[0].ocr_provider == "manual_text"
    assert rows[0].parsed_amount_cents == 2900
    assert rows[0].raw_text.startswith("星巴克")


def test_expense_response_does_not_fall_back_to_raw_text_column(
    client, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.raw_text = "column-only stale text"
        db.commit()

    response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)

    assert response.status_code == 200, response.json()
    assert response.json()["raw_text"] is None


def test_expense_response_reads_raw_text_from_ocr_facts(
    client, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.raw_text = "stale mirror text"
        record_ocr_fact(
            db,
            OcrFactDraft(
                tenant_id="owner",
                expense_id=expense_id,
                ocr_provider="manual_text",
                raw_text="canonical fact text",
            ),
        )
        db.commit()

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)

    assert detail.status_code == 200, detail.json()
    assert detail.json()["raw_text"] == "canonical fact text"
    assert pending.status_code == 200, pending.json()
    assert any(
        item["id"] == expense_id and item["raw_text"] == "canonical fact text"
        for item in pending.json()
    )


def test_retry_ocr_appends_fact_each_time(
    client, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    runs = iter(
        [
            OcrResult(raw_text="retry one\n12.00", confidence=0.7, amount_cents=1200),
            OcrResult(raw_text="retry two\n13.00", confidence=0.8, amount_cents=1300),
        ]
    )
    monkeypatch.setattr(
        "app.services.expense_service._ocr.extract_ocr_result",
        lambda expense: next(runs),
    )
    monkeypatch.setattr(
        "app.services.expense_service._ocr._active_provider_name",
        lambda: "mock",
    )

    first = client.post(
        f"/api/expenses/{expense_id}/ocr/retry", headers=identity.app_headers
    )
    second = client.post(
        f"/api/expenses/{expense_id}/ocr/retry", headers=identity.app_headers
    )

    assert first.status_code == 200, first.json()
    assert second.status_code == 200, second.json()
    rows = _facts(expense_id)
    assert [row.raw_text for row in rows] == ["retry two\n13.00", "retry one\n12.00"]
    assert all(row.ocr_provider == "mock" for row in rows)
