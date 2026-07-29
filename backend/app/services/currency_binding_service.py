"""ADR-0061 C02 bridge (PR#255 R9): write-time currency-binding drift gate.

``FX_HOME_CURRENCY_CODE`` (env) is the installation home currency's CURRENT
configured value, not the persisted versioned binding of ADR-0061 C02 — the
full answer (a persisted binding row + revision handshake, so a restart can't
silently reinterpret existing facts) belongs to the follow-up 0061 parity
slice. Until it lands, this module is the minimal fail-closed bridge: every
write path that stamps a new fact with the env currency first checks the env
value against the ``home_currency_code`` of ALREADY persisted facts. An empty
installation passes (first record claims the binding); a single shared
currency passes; any disagreement is configuration drift (C02 forbids
hot-switching) and the write is rejected with ``currency_binding_drift``.

Read paths never come here (they degrade via
:func:`app.services.currency_common.home_currency_code_or_none`); a
misconfigured env still raises ``currency_not_supported`` on the write path
before this gate runs.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.models import (
    AppMeta,
    Budget,
    CategoryRule,
    Debt,
    Expense,
    Goal,
    MemberRepaymentProposal,
    MonthlyIncomePlan,
    RecurringItem,
    RepaymentDraft,
)
from app.services.app_meta_service import get_value
from app.services.currency_common import home_currency_code, home_currency_code_or_none
from app.services.time_service import now_utc

# ADR-0075 的最小绑定标记（0061 C02 持久绑定的最小前驱：write-once 单行键，无
# revision 握手——首次以 env 盖章的写在同 key 上 claim，其后写只读裁决）。
INSTALLATION_HOME_CURRENCY_KEY = "installation_home_currency"


# Tables that participate in home-currency semantics. Repayments are covered
# by their parent Debt's frozen currency, so they are not queried separately.
# NOTE: the lookups are unrolled on purpose — a query inside a for-loop body
# trips the codebase audit's N+1 detector.
def assert_currency_binding_consistent(db: Session, home: str) -> None:
    """Fail closed when the env binding drifts from any persisted home currency.

    裁决序（R13-1 绑定标记感知）：①有绑定事实（codes 非空）→ 任一与 env 不同 =
    配置漂移 → 409 ``currency_binding_drift``；②codes 空 → 读 AppMeta 绑定标记
    （`installation_home_currency`，0075 的最小前驱、write-once）：标记==env →
    放行；标记≠env → drift 拒；无标记且无任何无绑定金额行 → 放行并同事务 claim
    标记=env（首写 claim binding，解 R12-F「先建绑定事实恰是被拒操作」死锁）；
    无标记但有无绑定行（CNY 时代遗留整数）→ env≠CNY 拒
    ``currency_binding_unresolved``，env==CNY 放行并自愈补标。
    ``record_repayment`` 不经此库级门（外币路径在 _repayment 按笔拒，R12-C）。
    """
    codes: set[str] = set()
    codes.update(db.scalars(select(Debt.home_currency_code).distinct()))
    codes.update(db.scalars(select(Expense.home_currency_code).distinct()))
    codes.update(db.scalars(select(MemberRepaymentProposal.home_currency_code).distinct()))
    codes.update(db.scalars(select(RepaymentDraft.home_currency_code).distinct()))
    if any(code != home for code in codes):
        raise AppError("currency_binding_drift", status_code=409)
    if codes:
        return
    marker = get_value(db, INSTALLATION_HOME_CURRENCY_KEY)
    if marker is not None:
        if marker != home:
            raise AppError("currency_binding_drift", status_code=409)
        return
    has_unbound = (
        db.scalar(select(Budget.id).limit(1)) is not None
        or db.scalar(select(Goal.id).limit(1)) is not None
        or db.scalar(select(MonthlyIncomePlan.id).limit(1)) is not None
        or db.scalar(select(RecurringItem.id).limit(1)) is not None
        # P1-1：带金额条件的分类规则同携币种语义（amount_*_cents 无币种列，
        # 引擎按绑定币种解释）—— 计入无绑定证据集；纯关键词/分类规则与已删
        # 墓碑窄豁免（不携币种语义，不拖死首写）。
        or db.scalar(
            select(CategoryRule.id)
            .where(CategoryRule.deleted_at.is_(None))
            .where(
                (CategoryRule.amount_min_cents.isnot(None))
                | (CategoryRule.amount_max_cents.isnot(None))
            )
            .limit(1)
        )
        is not None
    )
    if not has_unbound:
        _claim_binding_marker(db, home)
        return
    if home != DEFAULT_HOME_CURRENCY_CODE:
        raise AppError("currency_binding_unresolved", status_code=409)
    _claim_binding_marker(db, home)


def assert_rule_amount_write_binding(db: Session, carries_amount: bool) -> None:
    """分类规则金额阈值的窄域写门（P1-1；#258-R2 项5/6 精化）—— 阈值携币种语义但无
    币种列（引擎按绑定币种解释）。carries_amount = 至少一界被置为**非 null**（创建/改写/
    墓碑恢复视同携币种语义写）；清除全 null 与纯关键词规则不过门。env 仅在 carries_amount
    时惰性读 —— 无金额规则在 env 配错下也不吃 currency_not_supported。"""
    if carries_amount:
        assert_currency_binding_consistent(db, home_currency_code())


def assert_rule_restore_binding(db: Session, carries_amount: bool) -> None:
    """带金额规则的墓碑恢复视同携币种语义写（P1-1 + #258-R2 项7 + #258-R3 项4 收窄）——
    先读绑定标记：标记==env（安装绑定稳定，墓碑系标记后创建、币种无歧义）→ 走主门裁决；
    标记缺失或≠env → 墓碑时代不可判（无币种列、首写时软删对门不可见不得成为绕过通道）
    → 保守拒（unresolved）。纯关键词规则墓碑豁免。"""
    if not carries_amount:
        return
    home = home_currency_code()
    if get_value(db, INSTALLATION_HOME_CURRENCY_KEY) != home:
        raise AppError("currency_binding_unresolved", status_code=409)
    assert_currency_binding_consistent(db, home)


def resolve_read_home_currency_code(db: Session) -> str | None:
    """读路径金额口径（#258-R3 项2，与写时主门同源的裁决序）：绑定事实（Debt/Expense/
    Proposal/RepaymentDraft 四表 distinct 恰一码 —— legacy 无标记安装的 record 权威臂，
    标记只在新受门写时补盖）→ 绑定标记 → env；多码混存（drift 异常态）→ None
    （调用方 fail closed，拒绝显示金额）。展开式四表 distinct（N+1 审计规避；
    渲染路径每请求至多一次）；事实臂只读不补盖（标记 claim 是写路径职责）。"""
    codes: set[str] = set()
    codes.update(db.scalars(select(Debt.home_currency_code).distinct()))
    codes.update(db.scalars(select(Expense.home_currency_code).distinct()))
    codes.update(db.scalars(select(MemberRepaymentProposal.home_currency_code).distinct()))
    codes.update(db.scalars(select(RepaymentDraft.home_currency_code).distinct()))
    if len(codes) > 1:
        return None
    if codes:
        return codes.pop()
    marker = get_value(db, INSTALLATION_HOME_CURRENCY_KEY)
    if marker is not None:
        return marker
    return home_currency_code_or_none()


def _claim_binding_marker(db: Session, home: str) -> None:
    """同事务写入绑定标记（不 commit —— 与调用方的首笔事实写同生共死）。

    R15b-5：并发首写同 key PK 撞不算失败 —— savepoint 内插入撞键后重读，现有
    标记==env 即视为 claim 成功（同值并发；撞键即胜者已提交、对读可见），
    标记!=env 抛 drift（真冲突）。调用方（如 goal create）的 catch-all
    `except IntegrityError` 不再把标记竞态误报为业务重名（409）。
    """
    try:
        with db.begin_nested():
            db.add(AppMeta(key=INSTALLATION_HOME_CURRENCY_KEY, value=home, updated_at=now_utc()))
    except IntegrityError:
        if get_value(db, INSTALLATION_HOME_CURRENCY_KEY) == home:
            return
        raise AppError("currency_binding_drift", status_code=409) from None
