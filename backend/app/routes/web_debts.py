"""/web/debts page (ADR-0049 债务域 · web 面 slice 1).

只读欠款列表，镜像 Android ``DebtListScreen`` 的紧凑行：左侧对手方名 + 方向徽章
(应付/应收) + 清偿状态徽章 (未结清/已结清/已作废)，右侧本位币剩余金额 (英雄) + 本金
脚注。复用 ``GET /api/debts`` 背后的同一个 ``list_debts`` (DebtListResponse)，所以
/web 与 Android 看到完全相同的行 (§14 三端视觉同步)。

**纯只读**：记一笔 / 还款 / 调整 / 作废 / 成员还款确认全部是 writer-only 的写动作，
留在 Android + ``/api`` 上 (本页不出 form)。成员债的关系化框架 (Communal not Market,
slice 8e ②) 落在**详情**面 (slice 2)，列表是中性索引 —— 与 Android 列表一致：列表行对
成员/外部债统一用会计向标签 (``DebtListScreen.DebtRow`` 即如此)，关系叙述在详情卡里。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.debt_service import list_debts

router = APIRouter(prefix="/web", tags=["web"])

# 镜像 Android 债务标签词汇 (DebtGoalLabels.kt + strings_stats_budget.xml)，让 /web 与
# Android 渲染**同一套**中文 (三端 copy 同步)。方向是会计向 应付/应收 (成员 + 外部一致，
# 与 Android 列表行相同 —— 关系化框架在详情面 slice 2，不在紧凑索引)。
_DIRECTION_LABELS = {"i_owe": "应付", "owed_to_me": "应收"}
_STATUS_LABELS = {"open": "未结清", "cleared": "已结清", "voided": "已作废"}
# 状态色调镜像 debtLinkStatusTone：cleared→ok(成功)、voided→danger、open→neutral(默认)。
_STATUS_TONE = {"open": "", "cleared": "ok", "voided": "danger"}
# 无 counterparty_label 时的回退名 (debt_goal_counterparty_member / _external)。
_COUNTERPARTY_FALLBACK = {"member": "家庭成员", "external": "外部欠款"}


def _debt_view(debt) -> dict:
    name = (debt.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK.get(
        debt.counterparty_type, _COUNTERPARTY_FALLBACK["external"]
    )
    return {
        "public_id": debt.public_id,
        "name": name,
        "direction_label": _DIRECTION_LABELS.get(debt.direction, "应付"),
        "status_label": _STATUS_LABELS.get(debt.status, "未结清"),
        "status_tone": _STATUS_TONE.get(debt.status, ""),
        # 金额走本位币 (remaining/principal 是服务端冻结的本位币分)，外币明细留详情面。
        "remaining_label": _home_amount_label(
            debt.remaining_amount_cents, debt.home_currency_code
        ),
        "principal_label": _home_amount_label(
            debt.principal_amount_cents, debt.home_currency_code
        ),
    }


@router.get("/debts", response_class=HTMLResponse)
def web_debts(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    listing = list_debts(db, tenant_id=selected_id)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["debts"] = [_debt_view(debt) for debt in listing.items]
    return templates.TemplateResponse(request=request, name="debts.html", context=ctx)
