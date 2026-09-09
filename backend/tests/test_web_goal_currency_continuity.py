"""Original goal amounts and submission identity survive currency refusals."""

import pytest

from tests._web_native_form_support import hidden_post_forms
from tests.test_web_goal_edit_continuity import _editor, _goal


def test_jpy_goal_editor_uses_recorded_units_under_cny_runtime(web_client, identity):
    runtime = web_client.get("/api/system/runtime-compatibility", headers=identity.app_headers).json()
    assert runtime["capabilities"]["currency"]["home_currency_code"] == "CNY"
    goal = _goal(web_client, identity, home_currency_code="JPY", amount_minor=1200)
    action, fields = _editor(web_client, goal["public_id"])
    assert fields["home_currency_code"] == "JPY"
    editor = web_client.get(action, params={"ledger_id": "owner"})
    assert 'name="target_amount_yuan" value="1200"' in editor.text
    assert "目标金额（JPY，仅支持整数）" in editor.text
    listing = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert "JPY 0 / 1200" in listing.text
    fields.update(name="日元目标调整", month="2026-05", category="餐饮", target_amount_yuan="1500")
    saved = web_client.post(action, data=fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    canonical = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert canonical["home_currency_code"] == "JPY"
    assert canonical["target_amount_cents"] == 1500
    assert canonical["row_version"] == goal["row_version"] + 1


@pytest.mark.parametrize(("submitted_currency", "status"), [("", 422), ("JPY", 409)])
def test_goal_edit_currency_refusal_keeps_raw_amount_key_and_occ(
    web_client, identity, submitted_currency, status,
):
    goal = _goal(web_client, identity)
    action, fields = _editor(web_client, goal["public_id"])
    fields.update(name="尚未保存的输入", month="2026-05", category="交通",
        target_amount_yuan="001200", home_currency_code=submitted_currency)
    refused = web_client.post(action, data=fields)
    assert refused.status_code == status, refused.text
    assert 'name="target_amount_yuan" value="001200"' in refused.text
    assert 'name="name" value="尚未保存的输入"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    for key in ("home_currency_code", "idempotency_key", "expected_row_version", "ledger_id"):
        assert retained[key] == fields[key]
    assert ">保存修改</button>" not in refused.text
    assert "在新窗口打开当前目标" in refused.text
    reviewed = web_client.post(action, data={**fields, "review_latest": "true"})
    assert reviewed.status_code == 200
    reviewed_fields = hidden_post_forms(reviewed.text)[action]
    # CSRF is a fresh transport token; original command identity must stay fixed.
    assert {key: value for key, value in reviewed_fields.items() if key != "csrf_token"} == {
        key: value for key, value in retained.items() if key != "csrf_token"
    }
    unchanged = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert unchanged == goal


def test_goal_create_without_currency_keeps_original_form_and_creates_nothing(web_client, identity):
    action = "/web/goals/create"
    page = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    fields = hidden_post_forms(page.text)[action]
    assert fields["home_currency_code"] == "CNY" and fields["idempotency_key"]
    fields.pop("home_currency_code")
    fields.update(name="尚未发送的目标", category="交通", target_amount_yuan="001200.00")
    refused = web_client.post(action, data=fields)
    assert refused.status_code == 422, refused.text
    assert 'name="target_amount_yuan" value="001200.00"' in refused.text
    assert 'name="name" value="尚未发送的目标"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    assert retained["home_currency_code"] == ""
    for key in ("idempotency_key", "month", "ledger_id"):
        assert retained[key] == fields[key]
    assert ">保存目标</button>" not in refused.text
    current = web_client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["items"] == []
