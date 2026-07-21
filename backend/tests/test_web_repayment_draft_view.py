"""Pure view-model pins for the /web repayment-draft review rows (slice C3).

从 test_web_repayment_drafts.py 拆出守 files_over_500：HTTP 层断言渲染文本，
这里直接钉 _audit_row_view 的视图字典——pill TONE、逐项 is_suggested/is_selected
标志、每行幂等键存在性、以及 API 无法构造的 外部欠款 防御 fallback。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.routes.web_repayment_drafts import _audit_row_view
from app.services.debt_service import RepaymentDraftAuditRow
from app.services.debt_service._repayment_draft_match import RepaymentMatchCandidate


# ── tones + per-choice flags + prefixes + 防御 fallback ──
# Pin the view dict directly: the HTTP tests check rendered HTML substrings, but not the
# pill TONE, the per-choice is_suggested/is_selected flags, or the defensive 外部欠款
# fallback (an unconstructable null-label external Debt via the API — only reachable by
# building the audit row directly).
def _row(**overrides) -> RepaymentDraftAuditRow:
    base = {
        "source": "alipay",
        "amount_cents": 20000,
        "home_currency_code": "CNY",
        "merchant_label": "花呗",
        "captured_at": datetime(2026, 6, 18, 4, 0, tzinfo=UTC),
        "status": "pending",
        "linked_debt_label": None,
        "has_suggestion": False,
        "suggested_debt_label": None,
    }
    base.update(overrides)
    return RepaymentDraftAuditRow(**base)


def test_view_pending_with_suggestion() -> None:
    view = _audit_row_view(
        _row(
            has_suggestion=True,
            suggested_debt_label="花呗",
            suggested_debt_public_id="debt-1",
            target_debts=(
                RepaymentMatchCandidate(
                    public_id="debt-1",
                    counterparty_label="花呗",
                    remaining_amount_cents=50000,
                    row_version=7,
                ),
                RepaymentMatchCandidate(
                    public_id="debt-2",
                    counterparty_label="借呗",
                    remaining_amount_cents=30000,
                    row_version=2,
                ),
            ),
        )
    )
    assert view["status_label"] == "待复核"
    assert view["status_tone"] == ""  # pending is neutral
    assert view["provenance"] == "系统猜测对应:花呗"
    assert view["recede"] is False
    assert view["is_pending"] is True
    assert "linked_line" not in view
    assert view["source_label"] == "支付宝还款"  # mirrors Android source label (§14)
    assert view["amount_label"] == "¥200.00"
    assert view["idempotency_key"]  # 每行一套键 (uuid 文本)
    assert view["targets"] == [
        {
            "public_id": "debt-1",
            "row_version": 7,
            "name": "花呗",
            "remaining_label": "¥500.00",
            "is_suggested": True,  # 服务端建议项拿徽标+主按钮
            "is_selected": False,
        },
        {
            "public_id": "debt-2",
            "row_version": 2,
            "name": "借呗",
            "remaining_label": "¥300.00",
            "is_suggested": False,
            "is_selected": False,
        },
    ]


def test_view_pending_attempted_target_is_marked() -> None:
    # 422 原地重渲染：路由把 attempted target 传回视图，回填「刚才选择」。
    view = _audit_row_view(
        _row(
            target_debts=(
                RepaymentMatchCandidate(
                    public_id="debt-9",
                    counterparty_label=None,  # 防御：无名 → 外部欠款 fallback
                    remaining_amount_cents=30000,
                    row_version=2,
                ),
            ),
        ),
        attempted_target="debt-9",
    )
    assert "provenance" not in view
    assert view["targets"][0]["is_selected"] is True
    assert view["targets"][0]["name"] == "外部欠款"


def test_view_pending_without_targets_has_empty_choices() -> None:
    view = _audit_row_view(_row())
    assert view["targets"] == []
    assert view["is_pending"] is True


def test_view_confirmed_shows_linked_and_not_suggestion() -> None:
    view = _audit_row_view(_row(status="confirmed", linked_debt_label="招商信用卡"))
    assert view["status_label"] == "已记账"
    assert view["status_tone"] == "ok"
    assert view["linked_line"] == "已记到:招商信用卡"
    assert view["is_pending"] is False
    assert "provenance" not in view  # a resolved draft never carries the ephemeral suggestion
    assert "idempotency_key" not in view  # resolved rows carry no action context
    assert view["recede"] is False


def test_view_confirmed_null_label_falls_back_to_external_name() -> None:
    # Defensive fallback: a referenced external Debt always has a label, but the view must
    # never render 「已记到:None」 if it ever were null.
    view = _audit_row_view(_row(status="confirmed", linked_debt_label=None))
    assert view["linked_line"] == "已记到:外部欠款"


def test_view_dismissed_recedes_neutral() -> None:
    view = _audit_row_view(_row(status="dismissed"))
    assert view["status_label"] == "已忽略"
    assert view["status_tone"] == "muted"  # 永不 danger
    assert view["recede"] is True
    assert "idempotency_key" not in view
