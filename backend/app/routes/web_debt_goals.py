"""/web 桌面账本 · 还债目标进度 (ADR-0049 债务域 web 面 slice 4).

列出本账本的 ``debt_repayment`` 目标 + 清偿进度，并把创建、关联欠款调整、目标日期、
复核、归档与恢复收成同一条完整 Web 产品链。镜像 Android ``DebtPlanProgress``：
成员/混装 = **件数英雄**(一格=一笔=一次两清)，金额成弱化副文案(成员永不带「欠」、混币整条
隐藏)；**仅纯外部目标**显 businesslike KPI(``three_state`` 琥珀非红 + 还清投影三态诚实)。
``composition``(Member/External/Mixed/Empty) **web 端从 ``linked_debts[].counterparty_type``
派生**(后端不序列化该枚举，逐字镜像 Android ``DebtGoalComposition``，含 Empty 短路)；KPI 块
gate ``== External``(用 ==External 而非 !=Member 以排除 Mixed)。成员债**永不 danger**(红线②)。
读路径走 ``list_debt_repayment_goals``(``persist_achievement=False``，viewer 读永不锁存)；
写路径走 goal-debt 专属幂等命令（幂等 claim → OCC → 目标与成功记录同事务提交）。
成员行文案复用 ``web_debts`` 的 ``_MEMBER_*`` 标签(扩而非重写)；目标级文案逐字镜像
``strings_stats_budget.xml`` 的 ``debt_plan_*`` / ``debt_kpi_payoff*`` / ``debt_three_state_*``。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
)
from app.routes.web_debt_goal_views import (
    _render_debt_goals,
)
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalTargetDateRequest,
    GoalCreateRequest,
)
from app.services.goal_debt_repayment_service import (
    acknowledge_integrity_review_idempotently,
    archive_debt_repayment_goal_idempotently,
    create_debt_repayment_goal_idempotently,
    remove_voided_debt_goal_links_idempotently,
    replace_debt_repayment_goal_links_idempotently,
    restore_debt_repayment_goal_idempotently,
    set_debt_goal_target_date_idempotently,
)

router = APIRouter(prefix="/web/debt-goals", tags=["web"])


_STALE_MESSAGE = "计划已在其它端更新，请刷新后重新操作。"
_CREATE_VALIDATION = "请输入目标名称并至少选择一笔未结清欠款。"


def _action_scope(
    request: Request,
    db: Session,
    ledger_id: str,
) -> tuple[list, str]:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    return options, selected_id


def _expected_version(raw: str) -> int:
    expected = parse_form_row_version_token(raw)
    if expected is None:
        raise AppError("state_conflict", _STALE_MESSAGE, status_code=409)
    return expected


def _goal_error_message(exc: AppError) -> str:
    if exc.error == "state_conflict":
        return _STALE_MESSAGE
    if exc.error == "debt_not_found":
        return "可关联欠款已经变化，请刷新后重新选择。"
    return exc.message


def _action_error_redirect(
    selected_id: str,
    exc: AppError,
) -> RedirectResponse:
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        error=_goal_error_message(exc),
    )


@router.get("", response_class=HTMLResponse)
def web_debt_goals(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    error: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    return _render_debt_goals(
        request,
        db,
        options=options,
        selected_id=selected_id,
        message=msg,
        error=error,
    )


@router.post("/create", response_class=HTMLResponse)
def web_debt_goal_create(
    request: Request,
    ledger_id: str = Form(default=""),
    name: str = Form(default=""),
    debt_public_ids: list[str] = Form(default=[]),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options, selected_id = _action_scope(request, db, ledger_id)
    values = {
        "name": name,
        "selected_debt_ids": debt_public_ids,
        "idempotency_key": idempotency_key,
    }
    try:
        if not name.strip() or not debt_public_ids:
            raise AppError(
                "invalid_request",
                _CREATE_VALIDATION,
                status_code=422,
            )
        payload = GoalCreateRequest(
            name=name.strip(),
            goal_type="debt_repayment",
            debt_public_ids=debt_public_ids,
        )
        create_debt_repayment_goal_idempotently(
            db,
            tenant_id=selected_id,
            payload=payload,
            idempotency_key=idempotency_key.strip() or None,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        message = _goal_error_message(exc) if isinstance(exc, AppError) else _CREATE_VALIDATION
        return _render_debt_goals(
            request,
            db,
            options=options,
            selected_id=selected_id,
            error=message,
            create_values=values,
            status_code=422,
        )
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="还债目标已创建。",
    )


@router.post("/{public_id}/links", response_class=HTMLResponse)
def web_debt_goal_links(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    debt_public_ids: list[str] = Form(default=[]),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options, selected_id = _action_scope(request, db, ledger_id)
    try:
        payload = DebtGoalLinksReplaceRequest(
            expected_row_version=_expected_version(expected_row_version),
            debt_public_ids=debt_public_ids,
        )
        replace_debt_repayment_goal_links_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            payload=payload,
            idempotency_key=idempotency_key.strip() or None,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        if isinstance(exc, AppError) and exc.error == "state_conflict":
            return _action_error_redirect(selected_id, exc)
        return _render_debt_goals(
            request,
            db,
            options=options,
            selected_id=selected_id,
            error=(_goal_error_message(exc) if isinstance(exc, AppError) else "至少选择一笔欠款。"),
            link_values={public_id: debt_public_ids},
            status_code=422,
        )
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="已更新关联的欠款。",
    )


@router.post("/{public_id}/target-date", response_class=HTMLResponse)
def web_debt_goal_target_date(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    target_date: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options, selected_id = _action_scope(request, db, ledger_id)
    try:
        cleaned = target_date.strip()
        parsed_date = date.fromisoformat(cleaned) if cleaned else None
        payload = DebtGoalTargetDateRequest(
            expected_row_version=_expected_version(expected_row_version),
            target_date=parsed_date,
        )
        set_debt_goal_target_date_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            payload=payload,
            idempotency_key=idempotency_key.strip() or None,
        )
    except ValueError:
        db.rollback()
        return _render_debt_goals(
            request,
            db,
            options=options,
            selected_id=selected_id,
            error="请选择正确的还清日期。",
            target_values={public_id: target_date},
            status_code=422,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        if isinstance(exc, AppError) and exc.error == "state_conflict":
            return _action_error_redirect(selected_id, exc)
        return _render_debt_goals(
            request,
            db,
            options=options,
            selected_id=selected_id,
            error=(_goal_error_message(exc) if isinstance(exc, AppError) else "请选择正确的还清日期。"),
            target_values={public_id: target_date},
            status_code=422,
        )
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="还清日期已更新。",
    )


@router.post("/{public_id}/review/acknowledge")
def web_debt_goal_review_acknowledge(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _, selected_id = _action_scope(request, db, ledger_id)
    try:
        acknowledge_integrity_review_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            payload=DebtGoalIntegrityReviewRequest(
                expected_row_version=_expected_version(expected_row_version),
            ),
            idempotency_key=idempotency_key.strip() or None,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        app_error = (
            exc if isinstance(exc, AppError) else AppError("invalid_request", "暂时不能保留这次复核。", status_code=422)
        )
        return _action_error_redirect(selected_id, app_error)
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="已确认保留存档。",
    )


@router.post("/{public_id}/review/remove-voided")
def web_debt_goal_review_remove_voided(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _, selected_id = _action_scope(request, db, ledger_id)
    try:
        remove_voided_debt_goal_links_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=_expected_version(expected_row_version),
            idempotency_key=idempotency_key.strip() or None,
        )
    except AppError as exc:
        db.rollback()
        return _action_error_redirect(selected_id, exc)
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="已移除不再有效的欠款。",
    )


@router.post("/{public_id}/archive")
def web_debt_goal_archive(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _, selected_id = _action_scope(request, db, ledger_id)
    try:
        archive_debt_repayment_goal_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=_expected_version(expected_row_version),
            idempotency_key=idempotency_key.strip() or None,
        )
    except AppError as exc:
        db.rollback()
        return _action_error_redirect(selected_id, exc)
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="已归档目标。",
    )


@router.post("/{public_id}/restore")
def web_debt_goal_restore(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _, selected_id = _action_scope(request, db, ledger_id)
    try:
        restore_debt_repayment_goal_idempotently(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=_expected_version(expected_row_version),
            idempotency_key=idempotency_key.strip() or None,
        )
    except AppError as exc:
        db.rollback()
        return _action_error_redirect(selected_id, exc)
    return _web_redirect(
        "/web/debt-goals",
        selected_id,
        msg="目标已恢复。",
    )
