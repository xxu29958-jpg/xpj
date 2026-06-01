"""v1.1 PR-9: /web income-plans + /web budget-advise page smoke tests.

Loopback-only entry points. Each test follows the project pattern:
TestClient (loopback by default) + the ``identity`` fixture (which
sets up a default ledger and admin/owner identity).

Coverage:
- Both pages render 200 against a clean DB (no income plans yet).
- Income plan create form round-trips and shows up in the table.
- Archive + restore work and redirect back to the list.
- Budget advise page renders the discretionary breakdown and the
  "AI 未启用" hint when BUDGET_ADVISOR_PROVIDER=empty (the default).
- Budget advise page accepts run_advise=true and returns 200 even
  with no provider — never 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_income_plans_page_renders_empty(web_client: TestClient, *, identity) -> None:  # noqa: ARG001
    resp = web_client.get("/web/income-plans")
    assert resp.status_code == 200
    body = resp.text
    assert "收入计划" in body
    assert "还没有收入计划" in body


def test_income_plans_create_and_list(web_client: TestClient, *, identity) -> None:  # noqa: ARG001
    create_resp = web_client.post(
        "/web/income-plans/create",
        data={
            "label": "我的工资",
            "source_type": "salary",
            "amount_yuan": "10000",
            "pay_day": "10",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303

    list_resp = web_client.get("/web/income-plans")
    assert list_resp.status_code == 200
    body = list_resp.text
    assert "我的工资" in body
    # 10000 元 should render somewhere
    assert "10000.00" in body or "10,000.00" in body or "10000" in body


def test_income_plans_archive_and_restore(web_client: TestClient, *, identity) -> None:  # noqa: ARG001
    create_resp = web_client.post(
        "/web/income-plans/create",
        data={
            "label": "副业",
            "source_type": "freelance",
            "amount_yuan": "3000",
            "pay_day": "20",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    # ADR-0038 PR-B: archive/restore now carry an OCC token. Pull both the
    # public_id and the token out of the *rendered* archive form (real
    # round-trip), not a DB read — mirrors the recurring regression guard.
    import re
    list_body = web_client.get("/web/income-plans").text
    match = re.search(
        r'/web/income-plans/([0-9a-f-]+)/archive"[^>]*>.*?'
        r'name="expected_updated_at" value="([^"]*)"',
        list_body,
        re.DOTALL,
    )
    assert match is not None, "archive form + token should be on the page"
    pid, archive_token = match.group(1), match.group(2)
    assert archive_token, "archive form must render a non-empty expected_updated_at"

    archive_resp = web_client.post(
        f"/web/income-plans/{pid}/archive",
        data={"expected_updated_at": archive_token},
        follow_redirects=False,
    )
    assert archive_resp.status_code == 303

    after_archive = web_client.get("/web/income-plans").text
    # Archived plan should appear in the archived table with restore button
    assert "已归档" in after_archive
    assert "restore" in after_archive

    restore_match = re.search(
        re.escape(f"/web/income-plans/{pid}/restore") + r'"[^>]*>.*?'
        r'name="expected_updated_at" value="([^"]*)"',
        after_archive,
        re.DOTALL,
    )
    assert restore_match is not None, "restore form + token should be on the page"
    restore_token = restore_match.group(1)

    restore_resp = web_client.post(
        f"/web/income-plans/{pid}/restore",
        data={"expected_updated_at": restore_token},
        follow_redirects=False,
    )
    assert restore_resp.status_code == 303

    after_restore = web_client.get("/web/income-plans").text
    # Status-distinguishing assertion: "副业" (the label) renders in BOTH the
    # active and archived tables, so asserting it alone has no teeth — a failed
    # restore (stale token → still archived) would pass. The archived card is
    # guarded by {% if plans_archived %}, so after restoring the only plan the
    # "已归档" heading is gone. This is the PR-A P1#2 trap; assert the heading
    # disappears so a broken restore token actually fails the test.
    assert "副业" in after_restore
    assert "已归档" not in after_restore


def test_income_plans_rejects_bad_pay_day(web_client: TestClient, *, identity) -> None:  # noqa: ARG001
    resp = web_client.post(
        "/web/income-plans/create",
        data={
            "label": "x",
            "source_type": "salary",
            "amount_yuan": "100",
            "pay_day": "99",
        },
        follow_redirects=False,
    )
    # Service raises AppError -> 422 via the project handler
    assert resp.status_code == 422


def test_budget_advise_page_renders_with_default_empty_provider(
    web_client: TestClient, *, identity
) -> None:  # noqa: ARG001
    resp = web_client.get("/web/budget-advise")
    assert resp.status_code == 200
    body = resp.text
    assert "本月可自由支配" in body
    assert "AI 建议" in body
    # Default config keeps provider=empty, so the page must surface
    # "AI 未启用" hint rather than try to call out.
    assert "AI 未启用" in body or "empty" in body
    assert "BUDGET_ADVISOR_PROVIDER=empty" in body or "empty" in body


def test_budget_advise_accepts_query_params(
    web_client: TestClient, *, identity
) -> None:  # noqa: ARG001
    resp = web_client.get(
        "/web/budget-advise?savings_target_yuan=500&reserved_buffer_yuan=100"
    )
    assert resp.status_code == 200
    body = resp.text
    # The subtraction line should reflect the user-supplied values
    assert "500" in body
    assert "100" in body


def test_budget_advise_run_advise_with_empty_provider_is_safe(
    web_client: TestClient, *, identity
) -> None:  # noqa: ARG001
    # Even when the user clicks "调用 AI 建议", the empty provider path
    # must return 200 without making any HTTP call (run_advise skipped
    # internally because provider == 'empty').
    resp = web_client.get("/web/budget-advise?run_advise=true")
    assert resp.status_code == 200


def test_budget_advise_rejects_negative_savings(
    web_client: TestClient, *, identity
) -> None:  # noqa: ARG001
    resp = web_client.get("/web/budget-advise?savings_target_yuan=-1")
    assert resp.status_code == 422
