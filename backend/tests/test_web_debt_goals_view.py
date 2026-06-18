"""/web/debt-goals view-model derivation unit tests (ADR-0049 债务域 web 面 slice 4).

Pure (no-DB) tests for the ``web_debt_goals`` view-model helpers — they mirror Android
``DebtGoal`` / ``DebtPlanProgress`` / ``DebtKpiLabels`` derivation VERBATIM: composition
(Member/External/Mixed/Empty, voided dropped), count headline, amount sub-line (member never
带「欠」, mixed-currency suppressed), payoff 3-arm, three-state tone (at_risk 琥珀非红), per-link
rows (成员永不 danger / 外部 voided→danger), all-voided short-circuit, eval-badge tone. Split from
``test_web_debt_goals.py`` (HTTP path) to keep both files under the files_over_500 gate.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.routes.web_debt_goals import (
    _counted_links,
    _debt_goal_view,
    _external_kpi_view,
    _external_link_meta,
    _goal_composition,
    _goal_link_row,
    _member_link_note,
    _payoff_line,
    _plan_amount_line,
    _plan_headline,
    _shared_currency,
)
from app.schemas._goals import DebtGoalLinkView, DebtRepaymentEvaluation


def _link(
    *,
    status: str = "open",
    counterparty_type: str = "member",
    label: str | None = None,
    direction: str = "i_owe",
    principal: int = 10000,
    remaining: int = 10000,
    currency: str = "CNY",
) -> DebtGoalLinkView:
    return DebtGoalLinkView(
        debt_public_id=str(uuid4()),
        status=status,
        direction=direction,
        counterparty_type=counterparty_type,
        counterparty_label=label,
        principal_amount_cents=principal,
        remaining_amount_cents=remaining,
        home_currency_code=currency,
    )


def _eval(
    *,
    links: list[DebtGoalLinkView],
    evaluation_state: str = "in_progress",
    needs_review: bool = False,
    three_state: str | None = None,
    tracking_days: int | None = None,
    projected_payoff_date: date | None = None,
    target_date: date | None = None,
    days_since_last_activity: int | None = None,
) -> DebtRepaymentEvaluation:
    return DebtRepaymentEvaluation(
        goal_version=1,
        evaluation_state=evaluation_state,
        needs_review=needs_review,
        linked_debts=links,
        voided_debt_public_ids=[link.debt_public_id for link in links if link.status == "voided"],
        tracking_days=tracking_days,
        projected_payoff_date=projected_payoff_date,
        target_date=target_date,
        three_state=three_state,
        days_since_last_activity=days_since_last_activity,
    )


def _goal(evaluation: DebtRepaymentEvaluation, *, name: str = "还清", public_id: str = "pub") -> SimpleNamespace:
    """``_debt_goal_view`` reads only ``name`` / ``public_id`` / ``debt_repayment`` — stub the rest."""
    return SimpleNamespace(name=name, public_id=public_id, debt_repayment=evaluation)


def test_goal_composition_member_external_mixed_empty() -> None:
    assert _goal_composition([_link(counterparty_type="member")]) == "member"
    assert _goal_composition([_link(counterparty_type="external")]) == "external"
    assert _goal_composition(
        [_link(counterparty_type="member"), _link(counterparty_type="external")]
    ) == "mixed"
    assert _goal_composition([]) == "empty"


def test_goal_composition_drops_voided_before_deciding() -> None:
    # A voided external alongside an open member is NOT mixed — voided is dropped first (countedLinks).
    evaluation = _eval(
        links=[
            _link(counterparty_type="member", status="open"),
            _link(counterparty_type="external", status="voided"),
        ]
    )
    assert _goal_composition(_counted_links(evaluation)) == "member"


def test_plan_headline_member_arms() -> None:
    assert _plan_headline("member", cleared=0, total=2, remaining=2) == "这几笔，和家人一起慢慢清"
    assert _plan_headline("member", cleared=1, total=2, remaining=1) == "和家人两清了 1 笔 · 还剩 1 笔"
    assert _plan_headline("member", cleared=2, total=2, remaining=0) == "这几笔，和家人都两清啦"


def test_plan_headline_external_and_mixed() -> None:
    assert _plan_headline("external", cleared=1, total=3, remaining=2) == "已还清 1 / 3 笔"
    assert _plan_headline("mixed", cleared=1, total=3, remaining=2) == "已处理 1 / 3 笔"


def test_plan_amount_line_member_external_and_done() -> None:
    # Member never says 欠; uses 共/还剩. External uses 共/剩余. remaining_count==0 collapses to total only.
    assert _plan_amount_line("member", 30000, 20000, 2, "CNY") == "这几笔共 ¥300.00 · 还剩 ¥200.00"
    assert _plan_amount_line("external", 30000, 20000, 2, "CNY") == "共 ¥300.00 · 剩余 ¥200.00"
    assert _plan_amount_line("member", 30000, 0, 0, "CNY") == "这几笔共 ¥300.00"
    assert "欠" not in _plan_amount_line("member", 30000, 20000, 2, "CNY")


def test_shared_currency_none_when_mixed() -> None:
    assert _shared_currency([_link(currency="CNY"), _link(currency="CNY")]) == "CNY"
    assert _shared_currency([_link(currency="CNY"), _link(currency="USD")]) is None


def test_debt_goal_view_hides_amount_line_on_mixed_currency() -> None:
    evaluation = _eval(
        links=[
            _link(counterparty_type="member", currency="CNY"),
            _link(counterparty_type="member", currency="USD"),
        ]
    )
    view = _debt_goal_view(_goal(evaluation))
    assert "amount_line" not in view  # mixed currency → amount sub-line suppressed entirely


def test_payoff_line_projected_stale_insufficient() -> None:
    projected = _payoff_line(
        _eval(links=[_link(counterparty_type="external")], tracking_days=30,
              projected_payoff_date=date(2026, 9, 1))
    )
    assert projected["text"] == "按最近 30 天的进度，预计 2026 年 9 月前后还清"
    assert projected["tone"] == "neutral"
    stale = _payoff_line(
        _eval(links=[_link(counterparty_type="external")], days_since_last_activity=42)
    )
    assert stale["text"] == "已 42 天没有更新，估算可能已过期"
    assert stale["tone"] == "warn"  # amber, never danger
    insufficient = _payoff_line(_eval(links=[_link(counterparty_type="external")]))
    assert insufficient["text"] == "还没有足够数据估算还清日期"
    assert insufficient["tone"] == "neutral"


def test_external_kpi_three_state_tone_at_risk_is_amber_never_danger() -> None:
    ahead = _external_kpi_view(_eval(links=[_link(counterparty_type="external")],
                                     three_state="ahead", target_date=date(2027, 1, 1)))
    on_track = _external_kpi_view(_eval(links=[_link(counterparty_type="external")],
                                        three_state="on_track", target_date=date(2027, 1, 1)))
    at_risk = _external_kpi_view(_eval(links=[_link(counterparty_type="external")],
                                       three_state="at_risk", target_date=date(2027, 1, 1)))
    assert (ahead["three_state_label"], ahead["three_state_tone"]) == ("比计划提前", "ok")
    assert (on_track["three_state_label"], on_track["three_state_tone"]) == ("按计划进行", "")
    assert (at_risk["three_state_label"], at_risk["three_state_tone"]) == ("可能晚于计划", "amber")
    assert at_risk["three_state_tone"] != "danger"  # at_risk is amber, NOT red
    assert at_risk["target_label"] == "还清目标 2027 年 1 月"


def test_external_kpi_omits_three_state_and_target_when_absent() -> None:
    kpi = _external_kpi_view(_eval(links=[_link(counterparty_type="external")]))
    assert "three_state_label" not in kpi  # no badge without a three_state
    assert "target_label" not in kpi  # no deadline label without a target_date
    assert kpi["payoff"]["text"] == "还没有足够数据估算还清日期"


def test_goal_link_row_member_never_danger() -> None:
    open_row = _goal_link_row(_link(counterparty_type="member", status="open",
                                    principal=10000, remaining=4000, label="妈妈"))
    cleared_row = _goal_link_row(_link(counterparty_type="member", status="cleared",
                                       principal=10000, remaining=0, label="妈妈"))
    voided_row = _goal_link_row(_link(counterparty_type="member", status="voided",
                                      principal=10000, remaining=10000, label="弟弟"))
    assert open_row["status_label"] == "进行中" and open_row["status_tone"] == ""
    assert open_row["note"] == "这件事已对上大半"  # ratio 0.6 → most
    assert open_row["show_bar"] is True and open_row["fraction_percent"] == 60
    assert cleared_row["status_tone"] == "ok" and cleared_row["note"] == "已两清"
    assert cleared_row["fraction_percent"] == 100
    assert voided_row["status_label"] == "已不算" and voided_row["status_tone"] == ""
    assert voided_row["note"] == "这件事不算了"
    assert voided_row["recede"] is True and voided_row["show_bar"] is False
    for row in (open_row, cleared_row, voided_row):
        assert row["status_tone"] != "danger"  # member surface NEVER red (红线②)


def test_goal_link_row_external_meta_and_voided_danger() -> None:
    external = _goal_link_row(_link(counterparty_type="external", status="open",
                                    direction="i_owe", principal=50000, remaining=20000,
                                    label="招商信用卡"))
    assert external["name"] == "招商信用卡"
    assert external["meta"] == "应付 · 剩余 ¥200.00 · 本金 ¥500.00"
    assert external["show_bar"] is True
    voided_external = _goal_link_row(_link(counterparty_type="external", status="voided",
                                           principal=50000, remaining=50000))
    assert voided_external["status_label"] == "已作废" and voided_external["status_tone"] == "danger"


def test_external_link_meta_owed_direction_label() -> None:
    meta = _external_link_meta(_link(counterparty_type="external", direction="owed_to_me",
                                     principal=10000, remaining=10000))
    assert meta.startswith("应收 · ")


def test_member_link_note_open_progress_arms() -> None:
    assert _member_link_note(_link(counterparty_type="member", principal=10000, remaining=10000)) == "还没开始对账"
    assert _member_link_note(_link(counterparty_type="member", principal=10000, remaining=6000)) == "已经对上一部分"
    assert _member_link_note(_link(counterparty_type="member", principal=10000, remaining=2000)) == "这件事已对上大半"


def test_debt_goal_view_external_gates_kpi_mixed_and_member_excluded() -> None:
    external_view = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="external")]))
    )
    member_view = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="member")]))
    )
    mixed_view = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="member"), _link(counterparty_type="external")]))
    )
    assert "kpi" in external_view  # pure external → KPI block
    assert "kpi" not in member_view  # member → no KPI
    assert "kpi" not in mixed_view  # mixed excluded (gate is == External, not != Member)


def test_debt_goal_view_all_voided_short_circuit() -> None:
    view = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="external", status="voided")],
                    evaluation_state="not_evaluable", needs_review=True))
    )
    assert view["all_voided"] is True
    assert "headline" not in view and "kpi" not in view and "amount_line" not in view
    assert view["needs_review"] is True
    assert len(view["links"]) == 1  # the voided link is still listed (sunk)


def test_debt_goal_view_eval_badge_tones() -> None:
    in_progress = _debt_goal_view(_goal(_eval(links=[_link(counterparty_type="external")])))
    achieved = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="external", status="cleared", remaining=0)],
                    evaluation_state="achieved"))
    )
    not_evaluable = _debt_goal_view(
        _goal(_eval(links=[_link(counterparty_type="external", status="voided")],
                    evaluation_state="not_evaluable", needs_review=True))
    )
    assert (in_progress["eval_label"], in_progress["eval_tone"]) == ("进行中", "")
    assert (achieved["eval_label"], achieved["eval_tone"]) == ("已达成", "ok")
    assert (not_evaluable["eval_label"], not_evaluable["eval_tone"]) == ("待复核", "amber")
