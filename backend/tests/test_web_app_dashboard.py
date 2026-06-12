"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient

from app.services.time_service import current_month


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _row_id_set(html: str) -> set[str]:
    """Extract probable expense ids appearing in URLs of pending rows."""
    return set(re.findall(r"/web/expenses/(\d+)/edit", html))


def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试", *, identity) -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_root_renders_dashboard(web_client: TestClient) -> None:
    resp = web_client.get("/web", follow_redirects=False)
    assert resp.status_code == 200
    assert "仪表盘" in resp.text


def test_web_root_slash_redirects_to_root_with_ledger(web_client: TestClient) -> None:
    resp = web_client.get("/web/?ledger_id=owner", follow_redirects=False)
    assert resp.status_code in {303, 307}
    loc = resp.headers.get("location", "")
    assert loc.startswith("/web?") and "ledger_id=owner" in loc


def test_web_no_secret_leaks(web_client: TestClient, *, identity) -> None:
    """No token_hash, upload_key, pairing_code or absolute path in HTML."""
    pages = ["/web", "/web/pending", "/web/confirmed", "/web/reports", "/web/search"]
    for path in pages:
        resp = web_client.get(path)
        assert resp.status_code == 200, path
        body = resp.text
        # 64-char lower-hex token hashes
        assert not re.search(r"\b[0-9a-f]{64}\b", body), f"token_hash leaked in {path}"
        # Upload keys (~40 chars urlsafe). Anything starting with /u/ + token.
        assert "upload_key" not in body, f"upload_key keyword leaked in {path}"
        # Pairing code printed verbatim is fine as a label; ensure runtime value not echoed
        assert identity.upload_key not in body, f"upload_key value leaked in {path}"
        # Absolute Windows / POSIX paths
        assert not re.search(r"[A-Za-z]:\\\\[^\"'<>]+", body), f"abs path leaked in {path}"
        assert "/home/" not in body and "C:\\" not in body
        # Server endpoint / port leakage in普通用户面 — see ENGINEERING_RULES §10
        assert "127.0.0.1" not in body, f"loopback IP leaked in {path}"
        assert "localhost" not in body, f"localhost leaked in {path}"
        assert ":8000" not in body, f"server port leaked in {path}"


# ── A6: dashboard budget / goals 卡片进度条 ──────────────────────────────────
# Seed budget + goals into the *current accounting month* (the dashboard reads
# current_month("Asia/Shanghai")). A hardcoded month would silently produce an
# empty card once the wall-clock crosses into a different month — the
# month/timezone-alignment trap (test_month_timezone_alignment). The 15th at
# 04:00 UTC == 12:00 Asia/Shanghai is safely mid-month in both zones.


def _current_month_expense_time() -> str:
    return f"{current_month('Asia/Shanghai')}-15T04:00:00Z"


def _seed_budget_with_categories(
    client: TestClient,
    *,
    identity,
    dining_limit_cents: int,
    transit_limit_cents: int,
) -> None:
    month = current_month("Asia/Shanghai")
    resp = client.put(
        f"/api/budgets/monthly/{month}?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 100000,
            "category_budgets": [
                {"category": "餐饮", "amount_cents": dining_limit_cents},
                {"category": "交通", "amount_cents": transit_limit_cents},
            ],
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_goal(
    client: TestClient,
    *,
    identity,
    name: str,
    target_amount_cents: int,
    category: str | None = None,
) -> None:
    month = current_month("Asia/Shanghai")
    body = {"name": name, "month": month, "target_amount_cents": target_amount_cents}
    if category is not None:
        body["category"] = category
    resp = client.post(
        "/api/goals?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json=body,
    )
    assert resp.status_code == 201, resp.text


def _seed_confirmed_expense(
    client: TestClient, *, identity, amount_cents: int, merchant: str, category: str
) -> None:
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": _current_month_expense_time(),
        },
    )
    assert resp.status_code == 200, resp.text


def test_dashboard_data_payload_includes_budget_and_goals_top(
    web_client: TestClient, *, identity
) -> None:
    """A6: /web/dashboard/data carries per-category budget + per-goal progress
    rows the JS renderer turns into bars."""
    _seed_confirmed_expense(
        web_client, identity=identity, amount_cents=6000, merchant="餐厅", category="餐饮"
    )
    _seed_confirmed_expense(
        web_client, identity=identity, amount_cents=1500, merchant="地铁", category="交通"
    )
    _seed_budget_with_categories(
        web_client, identity=identity, dining_limit_cents=10000, transit_limit_cents=5000
    )
    _seed_goal(
        web_client, identity=identity, name="控制餐饮", target_amount_cents=10000, category="餐饮"
    )

    payload = web_client.get("/web/dashboard/data?ledger_id=owner").json()
    cards = payload["cards"]

    budget_top = cards["budget_top"]
    assert budget_top, "budget_top should carry per-category rows"
    by_name = {row["name"]: row for row in budget_top}
    # 餐饮: spent 6000 / limit 10000 = 60%
    assert by_name["餐饮"]["percent"] == 60
    assert by_name["餐饮"]["spent_yuan"] == "60.00"
    assert by_name["餐饮"]["limit_yuan"] == "100.00"
    assert by_name["餐饮"]["is_over"] is False
    # sorted by spend desc → 餐饮 (6000) before 交通 (1500)
    assert [row["name"] for row in budget_top] == ["餐饮", "交通"]

    goals_top = cards["goals_top"]
    assert goals_top, "goals_top should carry per-goal rows"
    goal = goals_top[0]
    assert goal["name"] == "控制餐饮"
    assert goal["percent"] == 60  # 6000 / 10000
    assert goal["state"] == "on_track"


def test_dashboard_renders_budget_and_goals_progress_bars(
    web_client: TestClient, *, identity
) -> None:
    """A6: the server-rendered fallback (no-JS path) draws the same cat-bar
    progress bars in the budget and goals cards."""
    _seed_confirmed_expense(
        web_client, identity=identity, amount_cents=6000, merchant="餐厅", category="餐饮"
    )
    _seed_budget_with_categories(
        web_client, identity=identity, dining_limit_cents=10000, transit_limit_cents=5000
    )
    _seed_goal(
        web_client, identity=identity, name="控制餐饮", target_amount_cents=10000, category="餐饮"
    )

    body = web_client.get("/web?ledger_id=owner").text
    # The bar list section renders server-side. (``cat-bar-fill`` alone would
    # be hollow — the pre-existing category-share card already emits it; the
    # load-bearing new-progress markers are ``cat-list--gap`` + the names.)
    assert "cat-list--gap" in body
    # Budget category name + goal name surface in the bar rows.
    assert "控制餐饮" in body


def test_dashboard_budget_overspent_row_marks_over_state(
    web_client: TestClient, *, identity
) -> None:
    """A6: an over-limit category budget row carries is_over + the「超」amount,
    and the fallback shows the red overspend label."""
    _seed_confirmed_expense(
        web_client, identity=identity, amount_cents=13000, merchant="餐厅", category="餐饮"
    )
    _seed_budget_with_categories(
        web_client, identity=identity, dining_limit_cents=10000, transit_limit_cents=5000
    )

    payload = web_client.get("/web/dashboard/data?ledger_id=owner").json()
    by_name = {row["name"]: row for row in payload["cards"]["budget_top"]}
    over = by_name["餐饮"]
    assert over["is_over"] is True
    assert over["overspent_yuan"] == "30.00"  # 13000 - 10000 = 3000 cents
    assert over["percent"] == 100  # capped at 100 even though 130%

    body = web_client.get("/web?ledger_id=owner").text
    assert "超 " in body  # overspend label「超 ¥30.00」renders in the fallback
