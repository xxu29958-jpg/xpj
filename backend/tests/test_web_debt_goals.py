"""/web/debt-goals 还债目标进度 (ADR-0049 债务域 web 面 slice 4).

只读：列本账本 debt_repayment 目标 + 清偿进度。镜像 Android DebtPlanProgress——成员/混装件数
英雄(金额弱化、成员永不带「欠」、混币隐藏)，仅纯外部目标显 KPI(three_state 琥珀非红 + 投影三态
诚实)，写动作留 App。本文件走真 route→service→DB→模板的 HTTP 路径；视图模型派生分支的纯单测拆在
``test_web_debt_goals_view.py``(守 files_over_500 门)。复用 conftest 的 ``web_client``(绕过 /web
loopback gate，viewer 解析为账本 owner)；``client`` 保 gate 验 remote-403。
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, DebtGoalLink, Goal, LedgerMember, Repayment
from app.services.time_service import now_utc

# ── ORM seed helpers ──────────────────────────────────────────────────────────


def _owner_account_id(db) -> int:
    owner_account_id = db.scalar(
        select(LedgerMember.account_id)
        .where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner")
        .limit(1)
    )
    assert owner_account_id is not None
    return owner_account_id


def _seed_debt_goal(*, name: str, links: list[dict]) -> str:
    """Seed an 'owner'-ledger debt_repayment goal + its DebtGoalLink set.

    Each ``links`` entry: ``{type: 'member'|'external', status: 'open'|'cleared'|'voided',
    principal, currency?, label?, direction?}``. ``cleared`` is driven by a Repayment that
    zeroes the fold (status column stays 'open' — derive_status returns cleared from the
    fold); ``voided`` sets ``Debt.status='voided'`` directly (derive_status reads it). The
    evaluator never persists for a read, so this is a faithful read-path seed.
    """
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        goal = Goal(
            tenant_id="owner",
            name=name,
            goal_type="debt_repayment",
            period="monthly",
            status="active",
            goal_version=1,
        )
        db.add(goal)
        db.flush()
        for spec in links:
            principal = spec["principal"]
            currency = spec.get("currency", "CNY")
            status_col = "voided" if spec["status"] == "voided" else "open"
            if spec["type"] == "member":
                member = Account(display_name=spec.get("label") or "家人")
                db.add(member)
                db.flush()
                debt = Debt(
                    tenant_id="owner",
                    owner_account_id=owner_id,
                    created_by_account_id=owner_id,
                    direction=spec.get("direction", "i_owe"),
                    counterparty_type="member",
                    counterparty_account_id=member.id,
                    counterparty_label=spec.get("label"),
                    principal_amount_cents=principal,
                    home_currency_code=currency,
                    status=status_col,
                    source_type="bill_split",
                    source_id=str(uuid4()),
                )
            else:
                debt = Debt(
                    tenant_id="owner",
                    owner_account_id=owner_id,
                    created_by_account_id=owner_id,
                    direction=spec.get("direction", "i_owe"),
                    counterparty_type="external",
                    counterparty_label=spec.get("label", "招商信用卡"),
                    principal_amount_cents=principal,
                    home_currency_code=currency,
                    status=status_col,
                    source_type="manual",
                )
            db.add(debt)
            db.flush()
            if spec["status"] == "cleared":
                db.add(
                    Repayment(
                        debt_id=debt.id,
                        amount_cents=principal,
                        paid_at=now_utc(),
                        actor_account_id=owner_id,
                        idempotency_key=str(uuid4()),
                    )
                )
            db.add(DebtGoalLink(goal_id=goal.id, goal_version=1, debt_id=debt.id))
        db.commit()
        return goal.public_id


def _seed_external_projection_goal(
    *,
    name: str,
    principal: int,
    paid: int,
    debt_days_ago: int,
    repayment_days_ago: int,
    target_date: date | None = None,
) -> str:
    """Seed a pure-external goal with one external debt + a backdated PARTIAL Repayment so the real
    KPI service produces a fresh / stale projection (the projection windows on ``created_at``).

    ``target_date`` drives three_state. Used to prove the KPI / amber-pill / projection template
    path renders through Jinja (not just the unit-tested view-model dict). The debt stays ``open``
    (partial paydown), so the goal is in_progress with a populated external KPI block.
    """
    now = now_utc()
    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        goal = Goal(
            tenant_id="owner",
            name=name,
            goal_type="debt_repayment",
            period="monthly",
            status="active",
            goal_version=1,
            target_date=target_date,
        )
        db.add(goal)
        db.flush()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_id,
            created_by_account_id=owner_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_label="招商信用卡",
            principal_amount_cents=principal,
            home_currency_code="CNY",
            status="open",
            source_type="manual",
            created_at=now - timedelta(days=debt_days_ago),
        )
        db.add(debt)
        db.flush()
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=paid,
                paid_at=now - timedelta(days=repayment_days_ago),
                created_at=now - timedelta(days=repayment_days_ago),
                actor_account_id=owner_id,
                idempotency_key=str(uuid4()),
            )
        )
        db.add(DebtGoalLink(goal_id=goal.id, goal_version=1, debt_id=debt.id))
        db.commit()
        return goal.public_id


# ── HTTP integration (route → service → DB → template) ─────────────────────────


def test_web_debt_goals_remote_returns_403(client: TestClient) -> None:
    # Without the web_client override the loopback gate rejects a non-loopback request.
    resp = client.get("/web/debt-goals")
    assert resp.status_code == 403


def test_web_debt_goals_empty_renders(web_client: TestClient) -> None:
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "还没有还债目标" in resp.text
    assert "dt-card--empty" in resp.text


def test_web_debt_goals_member_in_progress_is_communal(web_client: TestClient) -> None:
    # A member goal: 1 cleared + 1 open → count headline (笔数), success bar, member link rows,
    # amount sub-line never says 欠. Member surface never 应付/应收/danger; no external KPI block.
    _seed_debt_goal(
        name="和家人清账",
        links=[
            {"type": "member", "status": "cleared", "principal": 10000, "label": "妈妈"},
            {"type": "member", "status": "open", "principal": 20000, "label": "弟弟"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "和家人两清了 1 笔 · 还剩 1 笔" in resp.text  # count headline (cleared+remaining)
    assert "这几笔共" in resp.text and "还剩" in resp.text  # amount sub-line uses 共/还剩, never 欠
    assert "应付" not in resp.text and "应收" not in resp.text  # no accounting direction on a member goal
    assert "dt-pill danger" not in resp.text  # member never red
    # No external KPI block for a member composition (the projection line is the block's sentinel).
    assert "还没有足够数据估算还清日期" not in resp.text
    assert "妈妈" in resp.text and "弟弟" in resp.text  # link rows render counterparties
    assert "已两清" in resp.text  # cleared member link note (妈妈)
    assert "还没开始对账" in resp.text  # open member link note arm (弟弟, zero paydown) renders e2e


def test_web_debt_goals_member_all_cleared_done(web_client: TestClient) -> None:
    _seed_debt_goal(
        name="都清啦",
        links=[
            {"type": "member", "status": "cleared", "principal": 10000, "label": "妈妈"},
            {"type": "member", "status": "cleared", "principal": 5000, "label": "弟弟"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "这几笔，和家人都两清啦" in resp.text  # member done headline
    assert "已达成" in resp.text  # achieved eval badge
    assert "dt-pill ok" in resp.text  # achieved → ok tone


def test_web_debt_goals_external_in_progress_shows_kpi(web_client: TestClient) -> None:
    # External goal → "已还清 X / Y 笔" + external link meta (应付 · 剩余 · 本金) + KPI block.
    # With no paydown history the projection is insufficient (honest, never a fake date).
    _seed_debt_goal(
        name="还信用卡",
        links=[
            {"type": "external", "status": "open", "principal": 50000, "label": "招商信用卡"},
            {"type": "external", "status": "open", "principal": 30000, "label": "花呗"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "已还清 0 / 2 笔" in resp.text  # external count headline (cleared/total)
    assert "应付" in resp.text and "本金" in resp.text  # external link meta
    assert "还没有足够数据估算还清日期" in resp.text  # insufficient projection arm
    assert "招商信用卡" in resp.text


def test_web_debt_goals_external_projection_at_risk_renders_amber(web_client: TestClient) -> None:
    # Fresh projection (debt 30d ago, partial paydown 20d ago → days_since 20 < 35 stale floor) +
    # a far-past target_date → projected month > target month → at_risk. Proves the three_state
    # badge / target label / projected line flow through the real Jinja path AND the new
    # .dt-pill.amber tone renders amber (never danger) — the unit tests only assert the dict.
    _seed_external_projection_goal(
        name="还信用卡", principal=100000, paid=20000,
        debt_days_ago=30, repayment_days_ago=20, target_date=date(2024, 1, 1),
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "可能晚于计划" in resp.text  # at_risk three_state label
    assert "dt-pill amber" in resp.text  # at_risk badge renders amber...
    assert "dt-pill danger" not in resp.text  # ...NOT red (红线: at_risk 永不 danger)
    assert "还清目标" in resp.text  # target_date label
    assert "按最近" in resp.text and "前后还清" in resp.text  # projected payoff line (count/date-independent)


def test_web_debt_goals_external_projection_stale_renders_warn(web_client: TestClient) -> None:
    # Last paydown 40d ago (> 35d stale floor) → projection suppressed, the stale-warn line renders
    # (amber dg-projection--warn), not a fabricated date and not the insufficient arm.
    _seed_external_projection_goal(
        name="好久没还", principal=100000, paid=20000, debt_days_ago=60, repayment_days_ago=40,
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "估算可能已过期" in resp.text  # stale projection copy (day-count-independent fragment)
    assert "dg-projection--warn" in resp.text  # amber warn projection class
    assert "还没有足够数据估算还清日期" not in resp.text  # not the insufficient arm
    assert "dt-pill danger" not in resp.text  # stale is amber-toned, never red


def test_web_debt_goals_all_installment_renders_contract_payoff(web_client: TestClient) -> None:
    # §B: an all-installment goal renders the DETERMINISTIC contract payoff ("按分期合约 ... 还清"), NOT
    # the insufficient-data arm — even though tracking_days is None (no velocity). Closes the renderer
    # bug where projected-date-with-tracking_days-None fell through to "还没有足够数据".
    from datetime import UTC, datetime

    with SessionLocal() as db:
        owner_id = _owner_account_id(db)
        goal = Goal(
            tenant_id="owner", name="分期计划", goal_type="debt_repayment", period="monthly",
            status="active", goal_version=1,
        )
        db.add(goal)
        db.flush()
        debt = Debt(
            tenant_id="owner", owner_account_id=owner_id, created_by_account_id=owner_id,
            direction="i_owe", counterparty_type="external", counterparty_label="花呗分期",
            principal_amount_cents=120000, home_currency_code="CNY", status="open",
            source_type="manual", debt_kind="installment", installment_count=6,
            installment_period_months=1, created_at=datetime(2026, 3, 10, 4, 0, tzinfo=UTC),
        )
        db.add(debt)
        db.flush()
        db.add(DebtGoalLink(goal_id=goal.id, goal_version=1, debt_id=debt.id))
        db.commit()
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "按分期合约" in resp.text  # deterministic contract framing (not velocity "按最近 N 天")
    assert "2026 年 9 月" in resp.text  # 建账 2026-03 + 6 期 = 2026-09
    assert "还没有足够数据估算还清日期" not in resp.text  # NOT the insufficient arm (the fixed bug)


def test_web_debt_goals_mixed_has_no_kpi_block(web_client: TestClient) -> None:
    # Mixed composition → "已处理 X / Y 笔"; the KPI block is gated == External, so Mixed gets none.
    _seed_debt_goal(
        name="混装",
        links=[
            {"type": "member", "status": "open", "principal": 10000, "label": "妈妈"},
            {"type": "external", "status": "open", "principal": 20000, "label": "花呗"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "已处理 0 / 2 笔" in resp.text  # mixed headline
    assert "还没有足够数据估算还清日期" not in resp.text  # no KPI block for mixed
    assert "可能晚于计划" not in resp.text
    assert "dt-pill danger" not in resp.text


def test_web_debt_goals_voided_member_link_needs_review_never_red(web_client: TestClient) -> None:
    # A member goal with one open + one voided link → not_evaluable + needs_review amber note,
    # the voided link recedes (sunk) with a neutral 已不算 badge — member surface never red.
    _seed_debt_goal(
        name="有作废",
        links=[
            {"type": "member", "status": "open", "principal": 10000, "label": "妈妈"},
            {"type": "member", "status": "voided", "principal": 5000, "label": "弟弟"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "待复核" in resp.text  # not_evaluable eval badge
    assert "某关联欠款被判无效，需要你拿个主意" in resp.text  # needs_review descriptive note
    assert "复核与处理请在手机 App" in resp.text  # web read-only hint, no buttons
    assert "这件事不算了" in resp.text  # voided member link note
    assert "debt-card-sunk" in resp.text  # voided link recedes
    assert "dt-pill danger" not in resp.text  # member voided never red (红线②)


def test_web_debt_goals_all_voided_short_circuits(web_client: TestClient) -> None:
    _seed_debt_goal(
        name="全作废",
        links=[
            {"type": "external", "status": "voided", "principal": 10000, "label": "花呗"},
        ],
    )
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert "关联的欠款都已作废" in resp.text  # all-voided short-circuit text
    assert "已还清" not in resp.text and "已处理" not in resp.text  # no count headline
    assert "debt-card-sunk" in resp.text  # the voided link still listed, receded


def test_web_debt_goals_nav_and_planning_group(web_client: TestClient) -> None:
    resp = web_client.get("/web/debt-goals")
    assert resp.status_code == 200
    assert 'href="/web/debt-goals' in resp.text  # nav link present
    assert "<span>还债目标</span>" in resp.text
