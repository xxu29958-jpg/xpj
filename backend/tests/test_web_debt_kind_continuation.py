"""Original kind acceptance survives independently of current detail reads."""

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

import app.routes.web_debts as web_debts
from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey
from tests._web_native_form_support import hidden_post_forms
from tests.debt_repayment_goal_helpers import _clear_debt
from tests.test_debt_kind_setter import _set_owner_ledger_role
from tests.test_web_debt_actions import _create_debt, _detail, _form


def test_kind_native_select_keeps_exact_original_value_when_disabled_and_reopened():
    root = Path(__file__).parents[1]
    result = subprocess.run([shutil.which("node"), str(root / "tests/fixtures/debt_kind_draft_contract.cjs"),
        str(root / "app/static/web/manual-drafts.js"), str(root / "app/static/web/repayment-entry.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr


def test_terminal_debt_still_mounts_original_kind_input_when_same_identity_becomes_viewer(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    _clear_debt(web_client, identity.app_headers, debt)
    _set_owner_ledger_role("viewer")
    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    assert page.status_code == 200, page.text
    action = f"/web/debts/{debt['public_id']}/kind"
    recovery = hidden_post_forms(page.text)[action]
    assert recovery["idempotency_key"] == ""
    assert 'data-repayment-kind="debt-kind"' in page.text
    assert 'data-repayment-can-create="false"' in page.text
    assert 'data-repayment-can-recover="false"' in page.text


def test_kind_acceptance_is_not_reported_as_failure_when_detail_read_fails(web_client, identity, monkeypatch):
    debt = _create_debt(web_client, identity=identity)
    key = str(uuid4())

    def unavailable(*args, **kwargs):
        raise AppError("detail_unavailable", "详情暂时不可用", status_code=503)

    monkeypatch.setattr(web_debts, "_render_debt_detail", unavailable)
    response = web_client.post(f"/web/debts/{debt['public_id']}/kind",
        data=_form(debt, idempotency_key=key, debt_kind="revolving"))
    assert response.status_code == 200, response.text
    assert "原偿还方式更正已接受：循环往来" in response.text
    assert "当前详情暂时无法刷新" in response.text
    assert "data-repayment-ack=" in response.text and key in response.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["debt_kind"] == "revolving" and current["row_version"] == 2
    for field in ("principal_amount_cents", "paid_amount_cents", "remaining_amount_cents"):
        assert current[field] == debt[field]
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert claim.response_body == current


def test_kind_missing_receipt_preserves_original_for_review_without_fabricating_ack(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    action = f"/web/debts/{debt['public_id']}/kind"
    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    original = {**hidden_post_forms(page.text)[action], "debt_kind": "revolving"}
    accepted = web_client.post(action, data=original)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == original["idempotency_key"]))
        claim.response_body = None
        db.commit()
    response = web_client.post(action, data=original)
    assert response.status_code == 409, response.text
    assert "缺少原回执" in response.text
    assert 'data-repayment-result="accepted-review"' in response.text
    assert "data-repayment-ack=" not in response.text
    preserved = hidden_post_forms(response.text)[action]
    for field in ("idempotency_key", "expected_row_version", "origin_binding", "debt_public_id"):
        assert preserved[field] == original[field]
    assert '<option value="revolving" selected>' in response.text
    current = _detail(web_client, identity=identity, public_id=debt["public_id"])
    assert current["debt_kind"] == "revolving" and current["row_version"] == 2
