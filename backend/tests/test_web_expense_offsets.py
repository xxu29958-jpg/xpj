"""Real browser-command journeys for refund, chargeback, and reversal facts."""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient

from tests._web_native_form_support import hidden_post_forms
from tests.web_expense_fact_test_support import create_confirmed, row_version


def _fact_bundle(client: TestClient, expense_id: int, identity) -> dict:
    response = client.get(
        f"/api/expenses/{expense_id}/fact-bundle",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _money_fields(html, expense_id):
    action = f"/web/expenses/{expense_id}/offsets"
    form = next(match.group() for match in re.finditer(r"<form\b[^>]*>.*?</form>", html, re.S)
        if f'action="{action}"' in match.group() and 'id="offset-amount"' in match.group())
    return hidden_post_forms(form)[action]


def test_web_refund_replay_then_void_keeps_one_authoritative_fact(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    key = str(uuid4())
    form = {
        "ledger_id": "owner",
        "kind": "refund",
        "original_amount": "3.00",
        "accounting_date": "2026-09-03",
        "reason": "商家退回差价",
        "expected_row_version": str(row_version(web_client, expense_id, identity)),
        "idempotency_key": key,
    }

    first = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data=form,
        follow_redirects=False,
    )
    replay = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data=form,
        follow_redirects=False,
    )

    assert first.status_code == 303, first.text
    assert replay.status_code == 303, replay.text
    assert first.headers["location"].endswith("#fact-offsets")
    bundle = _fact_bundle(web_client, expense_id, identity)
    assert bundle["financial_summary"]["status"] == "partially_refunded"
    assert len(bundle["active_offsets"]) == 1
    offset = bundle["active_offsets"][0]
    assert offset["kind"] == "refund"
    assert offset["original_amount_minor"] == 300

    voided = web_client.post(
        f"/web/expenses/{expense_id}/offsets/{offset['public_id']}/voids",
        data={
            "ledger_id": "owner",
            "void_reason": "退款后来被商家撤回",
            "expected_row_version": str(offset["row_version"]),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )

    assert voided.status_code == 303, voided.text
    refreshed = _fact_bundle(web_client, expense_id, identity)
    assert refreshed["financial_summary"]["status"] == "confirmed"
    assert refreshed["active_offsets"] == []
    assert refreshed["recent_history"][0]["change_kind"] == "void"


def test_web_offset_conflict_keeps_original_until_explicit_nonwriting_review(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    stale_version = row_version(web_client, expense_id, identity)
    first = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data={
            "ledger_id": "owner",
            "kind": "refund",
            "original_amount": "1.00",
            "accounting_date": "2026-09-03",
            "reason": "先到的退款",
            "expected_row_version": str(stale_version),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )
    assert first.status_code == 303, first.text

    original = {
            "ledger_id": "owner",
            "kind": "chargeback",
            "original_amount": "2.00",
            "accounting_date": "2026-09-04",
            "reason": "银行卡争议仍需重试",
            "expected_row_version": str(stale_version),
            "idempotency_key": str(uuid4()),
            "original_currency_code": "CNY",
        }
    action = f"/web/expenses/{expense_id}/offsets"
    conflict = web_client.post(action, data=original)

    assert conflict.status_code == 409, conflict.text
    assert "银行卡争议仍需重试" in conflict.text
    assert "其它端" in conflict.text
    fresh_version = row_version(web_client, expense_id, identity)
    retained = _money_fields(conflict.text, expense_id)
    assert retained["expected_row_version"] == str(stale_version)
    assert retained["idempotency_key"] == original["idempotency_key"]
    before = _fact_bundle(web_client, expense_id, identity)
    reviewed = web_client.post(action, data={**original, "review_latest": "true"})
    assert reviewed.status_code == 200, reviewed.text
    prepared = _money_fields(reviewed.text, expense_id)
    assert prepared["expected_row_version"] == str(fresh_version)
    assert prepared["idempotency_key"] != original["idempotency_key"]
    assert prepared["draft_client_ref"] == original["idempotency_key"]
    assert _fact_bundle(web_client, expense_id, identity) == before
    assert web_client.post(action, data={**original, **prepared}, follow_redirects=False).status_code == 303
    after = _fact_bundle(web_client, expense_id, identity)
    assert len(after["active_offsets"]) == 2
    assert after["financial_summary"]["active_refunded_original_minor"] == 300


def test_web_reversal_has_no_amount_and_invalid_refund_keeps_input(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    version = row_version(web_client, expense_id, identity)
    invalid = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data={
            "ledger_id": "owner",
            "kind": "refund",
            "original_amount": "不是金额",
            "accounting_date": "2026-09-03",
            "reason": "保留这份草稿",
            "expected_row_version": str(version),
            "idempotency_key": str(uuid4()),
        },
    )
    assert invalid.status_code == 422, invalid.text
    assert "不是金额" in invalid.text
    assert "保留这份草稿" in invalid.text

    reversed_response = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data={
            "ledger_id": "owner",
            "kind": "reversal",
            "accounting_date": "2026-09-03",
            "reason": "这笔账不应计入",
            "expected_row_version": str(version),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )
    assert reversed_response.status_code == 303, reversed_response.text
    bundle = _fact_bundle(web_client, expense_id, identity)
    assert bundle["financial_summary"]["status"] == "reversed"
    assert bundle["active_offsets"][0]["kind"] == "reversal"


def test_web_fact_page_offsets_section_and_reversal_gate(
    web_client: TestClient,
    *,
    identity,
) -> None:
    """Page journey: section renders on confirmed; refund flips status pill and
    closes the reversal disclosure (server lineage status is the only gate)."""
    expense_id = create_confirmed(web_client, identity=identity)
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert 'id="fact-offsets"' in page.text
    assert "登记退款或拒付" in page.text
    assert "冲销这笔账单" in page.text
    # 金额输入是 text：422 草稿（如「不是金额」）不能被 number sanitization 清空。
    assert 'type="text" name="original_amount"' in page.text

    created = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data={
            "ledger_id": "owner",
            "kind": "refund",
            "original_amount": "3.00",
            "accounting_date": "2026-09-03",
            "reason": "商家退回差价",
            "expected_row_version": str(row_version(web_client, expense_id, identity)),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text

    partial = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert partial.status_code == 200, partial.text
    assert "部分退回" in partial.text
    assert "商家退款" in partial.text
    # 有 active 退款时冲销必然 409 expense_refund_exists：不渲染该 disclosure，
    # 改用指引文案；gate 事实源是 server lineage status，不是浏览器判断。
    assert 'id="offset-create-reversal"' not in partial.text
    assert "先撤销它们，才能冲销整笔账单" in partial.text


def test_web_void_race_conflict_surfaces_page_feedback(
    web_client: TestClient,
    *,
    identity,
) -> None:
    """Void losing the race: target already void elsewhere → 409 must still give
    honest page feedback even though the active row (its error slot) is gone."""
    expense_id = create_confirmed(web_client, identity=identity)
    created = web_client.post(
        f"/web/expenses/{expense_id}/offsets",
        data={
            "ledger_id": "owner",
            "kind": "refund",
            "original_amount": "3.00",
            "accounting_date": "2026-09-03",
            "reason": "商家退回差价",
            "expected_row_version": str(row_version(web_client, expense_id, identity)),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    bundle = _fact_bundle(web_client, expense_id, identity)
    offset = bundle["active_offsets"][0]

    first = web_client.post(
        f"/web/expenses/{expense_id}/offsets/{offset['public_id']}/voids",
        data={
            "ledger_id": "owner",
            "void_reason": "其它端先撤销了",
            "expected_row_version": str(offset["row_version"]),
            "idempotency_key": str(uuid4()),
        },
        follow_redirects=False,
    )
    assert first.status_code == 303, first.text

    # 旧 row token + 新 idempotency key 的迟到 void：目标已不在 active_offsets。
    stale = web_client.post(
        f"/web/expenses/{expense_id}/offsets/{offset['public_id']}/voids",
        data={
            "ledger_id": "owner",
            "void_reason": "迟到的重复撤销",
            "expected_row_version": str(offset["row_version"]),
            "idempotency_key": str(uuid4()),
        },
    )
    assert stale.status_code == 409, stale.text
    assert "原输入仍保留" in stale.text
    action = f'action="/web/expenses/{expense_id}/offsets/{offset["public_id"]}/voids"'
    assert action in stale.text
    assert 'value="迟到的重复撤销"' in stale.text
    assert 'data-offset-archived="true"' in stale.text
