"""/web/debts/{id} 分期计划卡 (ADR-0049 §B 完整 installment 三端补齐).

外部 installment 债详情页渲染「分期计划」卡：合约还清日 (措辞与 web_debt_goals._payoff_line + Android
debt_installment_payoff 逐字一致) / 已还期数**中性**进度 (绝不基于 paid==count 宣称已还清——提额调整会让 N/N
而剩余仍 >0, 完成由 status==cleared 决定, 故卡只对 open 渲染) / 每期**无息**估算 (本金÷期数 floor, 标「估算不含手续费」)。

拆出独立文件 (installment concern) 让 test_web_debts.py 留在 files_over_500 门下, 镜像 test_web_debt_proposals.py。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.routes.web_common import _home_amount_label
from app.routes.web_debts import _installment_view

# Uses the shared ``web_client`` / ``identity`` fixtures (conftest.py): web_client bypasses the
# /web loopback gate, identity carries the app auth headers for the create API.


def _create_installment_debt(
    web_client: TestClient,
    *,
    identity,
    principal_cents: int,
    count: int,
    period_months: int | None = None,
) -> dict:
    body: dict[str, object] = {
        "direction": "i_owe",
        "counterparty_type": "external",
        "counterparty_label": "花呗分期",
        "principal_amount_cents": principal_cents,
        "debt_kind": "installment",
        "installment_count": count,
    }
    if period_months is not None:
        body["installment_period_months"] = period_months
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    resp = web_client.post("/api/debts", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stub(**overrides) -> SimpleNamespace:
    """Minimal DebtResponse-shaped stub carrying exactly what ``_installment_view`` reads."""
    base = {
        "debt_kind": "installment",
        "status": "open",
        "principal_amount_cents": 120000,
        "installment_count": 12,
        "installment_period_months": 1,
        "installment_paid_count": 0,
        "installment_payoff_date": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_web_debt_detail_installment_renders_schedule_card(web_client: TestClient, *, identity) -> None:
    # §B: an open installment debt's detail page renders the schedule card mirroring Android.
    debt = _create_installment_debt(
        web_client, identity=identity, principal_cents=120000, count=12, period_months=1
    )
    resp = web_client.get(f"/web/debts/{debt['public_id']}")
    assert resp.status_code == 200
    body = resp.text
    assert "debt-installment-card" in body
    assert "分期计划" in body
    assert "共 12 期 · 每月一期" in body
    # 0 repayments → neutral 0/12 progress; the card NEVER claims 已还清 (that is status-gated).
    assert "已还 0 / 12 期" in body
    assert "按分期合约，预计" in body  # contractual payoff (mirrors web _payoff_line + Android)
    assert "每期约" in body and "估算不含手续费" in body  # interest-free per-period estimate


def test_installment_view_gates_and_computes() -> None:
    # Gate mirrors Android shouldShowInstallmentCard (isOpen && isInstallmentScheduled): a
    # non-installment / no-count / non-open debt yields None (no schedule card).
    assert _installment_view(_stub(debt_kind="unspecified"), "CNY") is None
    assert _installment_view(_stub(installment_count=None), "CNY") is None
    for closed in ("cleared", "voided"):
        assert _installment_view(_stub(status=closed), "CNY") is None

    view = _installment_view(
        _stub(installment_paid_count=5, installment_payoff_date=date(2027, 6, 15)), "CNY"
    )
    assert view["schedule_label"] == "共 12 期 · 每月一期"
    assert view["progress_label"] == "已还 5 / 12 期"
    assert view["payoff_label"] == "按分期合约，预计 2027 年 6 月还清"
    assert _home_amount_label(10000, "CNY") in view["per_period_label"]  # 120000 // 12 (floor)
    assert "估算不含手续费" in view["per_period_label"]

    # per_period is FLOOR (principal // count), same 口径 as Android installmentPerPeriodCents + backend
    # per_period — a floor-discriminating case: 125000 / 12 = 10416.67 → 10416 (NOT the rounded 10417).
    floored = _installment_view(_stub(principal_amount_cents=125000), "CNY")
    assert _home_amount_label(10416, "CNY") in floored["per_period_label"]

    # 红线 R1: paid_count beyond the total clamps to N/N (a raising adjustment), never 已还清.
    over = _installment_view(_stub(installment_paid_count=15), "CNY")
    assert over["progress_label"] == "已还 12 / 12 期"

    # Non-monthly period → the periodic schedule label variant (mirrors Android schedule_periodic).
    quarterly = _installment_view(_stub(installment_count=8, installment_period_months=3), "CNY")
    assert quarterly["schedule_label"] == "共 8 期 · 每 3 个月一期"
