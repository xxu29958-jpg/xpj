"""Sanitized regressions for independent notifications, retries and financial effects.

The reported shade includes 10.00 and 12.90 expenses plus transit and clipped
payment evidence; 29.33 was a separate capture.
No private original or notification body is included in this fixture.
"""

import json
from uuid import uuid4

import pytest
from api_contract_helpers import recognize_text_api, upload_png
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AccountMovement, Expense, ExpenseFunding, ExpenseSourceCandidate, OcrFact
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.ocr_service import OcrResult
from app.services.original_read_service import read_original_snapshot
from tests.test_expense_confirmation_funding import _draft, _selection, _submit
from tests.test_funds_accounts import _create_funds_account


def _cards(amounts=("10.00", "12.90")):
    return "\n".join(f"支付宝 · {hour}\n交易提醒\n你有一笔{amount}元的支出。\n商家：回归门店{index}号"
        for index, (hour, amount) in enumerate(zip(("17:49", "17:30", "16:10"), amounts, strict=False)))


def _apply(db, expense_id, text, **options):
    return apply_ocr_result_and_append_fact(db, expense=db.get(Expense, expense_id),
        result=OcrResult(raw_text=text, confidence=0.9), provider_name="manual_text", timezone_name="Asia/Shanghai", **options)


def _rows(db, root_id):
    return list(db.scalars(select(ExpenseSourceCandidate).where(ExpenseSourceCandidate.source_expense_id == root_id)
        .order_by(ExpenseSourceCandidate.event_index)))


def test_shade_candidates_have_independent_amount_evidence_and_exactly_once_confirmation(client, identity):
    root_id = upload_png(client, identity=identity)
    response = recognize_text_api(client, root_id, headers=identity.app_headers, raw_text=_cards())
    assert response.status_code == 200, response.text
    third = _draft(client, identity, 2933)
    with SessionLocal() as db:
        rows = _rows(db, root_id)
        assert len(rows) == 2 and len({row.event_key for row in rows}) == 2
        expenses = [db.get(Expense, row.expense_id) for row in rows]
        assert [expense.amount_cents for expense in expenses] == [1000, 1290]
        assert len({expense.image_path for expense in expenses}) == 2
        assert len({expense.image_hash for expense in expenses}) == 1
        for row, expense in zip(rows, expenses, strict=True):
            assert expense.status == "pending" and expense.original_currency_code == "CNY"
            assert expense.duplicate_status == "none"
            assert row.evidence["source_app"] == "alipay"
            assert row.evidence["source_text"] == _cards()
            assert row.evidence["parser_version"] == "receipt-fields-v10"
            assert row.evidence["raw_spans"] and row.evidence["candidates"]
            assert row.evidence["time_fragments"][0]["literal"] in {"17:49", "17:30"}
            fact = db.scalar(select(OcrFact).where(OcrFact.expense_id == expense.id).order_by(OcrFact.id.desc()))
            assert fact.parsed_amount_cents == expense.amount_cents
            assert json.loads(fact.evidence_json)["source_event"]["event_key"] == row.event_key
            with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
                    expected_sha256=expense.image_hash) as original:
                assert original.path.is_file()
        ids = [expense.id for expense in expenses] + [third["id"]]
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    for expense_id in ids:
        expense = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
        account = client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()
        body, key = {"funding": [_selection(account)]}, str(uuid4())
        response = _submit(client, identity, expense, body, key)
        assert response.status_code == 200, response.text
        assert _submit(client, identity, expense, body, key).json()["confirmation_receipt"] == response.json()["confirmation_receipt"]
    balance = client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()["balance_minor"]
    assert balance == 100000 - 1000 - 1290 - 2933
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExpenseFunding)) == 3
        assert db.scalar(select(func.count()).select_from(AccountMovement).where(AccountMovement.funding_id.is_not(None))) == 3


@pytest.mark.parametrize("amounts", [("10.00", "12.90", "29.33"), ("10.00", "10.00")])
def test_repeated_extraction_keeps_all_cards_and_does_not_edit_siblings(client, identity, amounts):
    root_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        _apply(db, root_id, _cards(amounts))
        db.commit()
        first = [(row.event_key, row.expense_id) for row in _rows(db, root_id)]
        assert len(first) == len(amounts)
        child = db.get(Expense, first[1][1])
        child.merchant = "人工核对商户"
        db.commit()
        _apply(db, root_id, _cards(amounts))
        db.commit()
        assert [(row.event_key, row.expense_id) for row in _rows(db, root_id)] == first
        assert db.get(Expense, child.id).merchant == "人工核对商户"
        assert all(db.get(Expense, row.expense_id).duplicate_status == "none" for row in _rows(db, root_id))


def test_later_provider_preserves_new_independent_candidates_without_overwriting_primary(client, identity):
    root_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        _apply(db, root_id, "支付成功\n支付金额29.33元")
        db.commit()
        _apply(db, root_id, _cards(), apply_to_draft=False)
        db.commit()
        assert db.get(Expense, root_id).amount_cents == 2933
        rows = _rows(db, root_id)
        assert len(rows) == 2 and all(row.expense_id != root_id for row in rows)
        assert [db.get(Expense, row.expense_id).amount_cents for row in rows] == [1000, 1290]


def test_failure_while_copying_original_rolls_back_all_candidates_and_retry_recovers(client, identity, monkeypatch):
    import app.services.expense_source_candidates as owner

    root_id = upload_png(client, identity=identity)
    original = owner.save_original_replenishment_bytes
    def fail_copy(*args, **kwargs):
        raise OSError("injected original storage failure")
    monkeypatch.setattr(owner, "save_original_replenishment_bytes", fail_copy)
    with SessionLocal() as db:
        with pytest.raises(OSError, match="injected"):
            _apply(db, root_id, _cards())
        db.rollback()
        assert not _rows(db, root_id)
        assert db.get(Expense, root_id).amount_cents is None
        assert db.scalar(select(func.count()).select_from(Expense)) == 1
        monkeypatch.setattr(owner, "save_original_replenishment_bytes", original)
        _apply(db, root_id, _cards())
        db.commit()
        assert len(_rows(db, root_id)) == 2


def test_selected_provider_claims_source_before_alternative_cards_without_replacing_canonical_fact(client, identity):
    from types import SimpleNamespace

    from app.services.expense_service._enrich import _apply_extractions
    from app.services.ocr_service import OcrExtraction, OcrRun

    root_id = upload_png(client, identity=identity)
    result = OcrResult(raw_text=_cards(), confidence=0.9)
    prepared = SimpleNamespace(ocr_run=OcrRun((OcrExtraction("manual_text", None, result, False),
        OcrExtraction("rapidocr", "rapidocr", result))))
    with SessionLocal() as db:
        _apply_extractions(db, db.get(Expense, root_id), prepared, "Asia/Shanghai")
        db.commit()
        assert len(_rows(db, root_id)) == 2
        assert db.scalar(select(func.count()).select_from(Expense)) == 2
        assert db.get(Expense, root_id).amount_cents == 1000
        fact = db.scalar(select(OcrFact).where(OcrFact.expense_id == root_id).order_by(OcrFact.id.desc()))
        assert fact.ocr_provider == "rapidocr" and fact.parsed_amount_cents == 1000


def test_human_amount_is_preserved_without_suppressing_first_new_candidate(client, identity):
    root = _draft(client, identity, 2933)
    reviewed = client.patch(f"/api/expenses/{root['id']}", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": root["row_version"], "original_amount_minor": 2933})
    assert reviewed.status_code == 200, reviewed.text
    with SessionLocal() as db:
        _apply(db, root["id"], _cards())
        db.commit()
        assert db.get(Expense, root["id"]).amount_cents == 2933
        assert [db.get(Expense, row.expense_id).amount_cents for row in _rows(db, root["id"])] == [1000, 1290]


def test_shade_preserves_non_expense_and_clipped_cards_without_advertisement_bleed(client, identity):
    text = ("城市公交卡 刷卡完成，交易金额：0.00元\n城市公交卡 充值金额：10.00元 卡内余…\n"
        "支付宝(2)\n交易提醒\n17:49\n你有一笔10.00元的支出。\n"
        "交易提醒\n17:30\n你有一笔12.90元的支出。\n"
        "购物优惠自动识别\n17:35\n广告商家优惠\n"
        "订单支付成功\n17:31\n美团\n您的订单内容被截断")
    root_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        _apply(db, root_id, text)
        db.commit()
        rows = _rows(db, root_id)
        assert len(rows) == 5
        expenses = [db.get(Expense, row.expense_id) for row in rows]
        assert [expense.amount_cents for expense in expenses] == [None, None, 1000, 1290, None]
        assert all(expense.status == "pending" for expense in expenses)
        assert all(expense.merchant != "广告商家优惠" for expense in expenses)
        assert any(candidate["value"] == 1000 and candidate["role"] == "topup"
            for candidate in rows[1].evidence["candidates"] if candidate["field"] == "amount_cents")
        assert rows[4].evidence["source_app"] == "meituan"
        assert [fragment["literal"] for fragment in rows[3].evidence["time_fragments"]] == ["17:30"]
        assert all(row.evidence["source_text"] == text for row in rows)
        assert db.scalar(select(func.count()).select_from(AccountMovement)) == 0
