"""Correction 命令执行（A1 Web 适配层责任之一）：actor 解析、ADR-0042
idempotency claim/重放、``correct_expense`` 调用与共享 commit。

幂等/OCC/权限的事实语义由后端服务拥有；本模块只做浏览器命令的执行编排：
- 每次表单渲染发一把 key，双击/刷新重提交经 claim 重放为同一条 revision；
- ``state_conflict`` → 调用方用冲突态重渲当前标量事实；行级意图只有在
  predecessor identity 仍匹配时才可保留；
- key 被别的意图占用（required/reused）→ 提示调用方换钥匙重试。

不做：表单解析/diff（_web_correction_form）、页面渲染（_web_correction_page）。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_session_common import resolve_web_actor
from app.schemas import ExpenseCorrectionRequest
from app.services.expense_correction_service import (
    CorrectionCommandClaim,
    claim_correction_command,
    complete_correction_command,
)
from app.services.expense_revision_service import revision_by_idempotency_key

CONFLICT_MSG = "这笔账单刚在其它端被修改，已载入最新基本信息；请核对明细和拆账，重新填写这次想改的内容后提交。"

_ROTATE_IDEMPOTENCY_ERRORS = frozenset({"idempotency_key_required", "idempotency_key_reused"})


@dataclass(frozen=True)
class CorrectionCommandOutcome:
    """执行结果：``error is None`` 即成功（含重放命中）。"""

    error: str | None = None
    error_code: str | None = None
    error_status: int = 422
    conflict: bool = False
    rotate_idempotency_key: bool = False


@dataclass(frozen=True)
class ClaimedWebCorrection:
    actor_account_id: int
    actor_device_id: int | None
    claim: CorrectionCommandClaim | None = None
    replayed: bool = False
    error: CorrectionCommandOutcome | None = None


def _command_error(exc: AppError) -> CorrectionCommandOutcome:
    if exc.error == "state_conflict":
        return CorrectionCommandOutcome(error=CONFLICT_MSG, error_status=409, conflict=True)
    return CorrectionCommandOutcome(
        error=exc.message,
        error_code=exc.error,
        error_status=web_form_error_status(exc),
        rotate_idempotency_key=exc.error in _ROTATE_IDEMPOTENCY_ERRORS,
    )


def claim_web_correction(
    db: Session,
    request: Request,
    *,
    expense_id: int,
    selected_id: str,
    expected_row_version: int,
    idempotency_key: str,
    intent_body: dict[str, object],
) -> ClaimedWebCorrection:
    """Claim the stable submitted intent before current-state diffing."""

    actor_account_id, actor_device_id = resolve_web_actor(db, request, selected_id)
    try:
        claim = claim_correction_command(
            db,
            tenant_id=selected_id,
            expense_id=expense_id,
            expected_row_version=expected_row_version,
            idempotency_key=idempotency_key,
            intent_body={**intent_body, "actor_account_id": actor_account_id},
        )
        if claim is None:
            revision = revision_by_idempotency_key(
                db, tenant_id=selected_id, idempotency_key=idempotency_key
            )
            if revision is None:
                raise AppError("server_error", status_code=500)
            return ClaimedWebCorrection(
                actor_account_id=actor_account_id,
                actor_device_id=actor_device_id,
                replayed=True,
            )
        return ClaimedWebCorrection(
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            claim=claim,
        )
    except AppError as exc:
        db.rollback()
        return ClaimedWebCorrection(
            actor_account_id=actor_account_id,
            actor_device_id=actor_device_id,
            error=_command_error(exc),
        )


def execute_correction(
    db: Session,
    *,
    claimed: ClaimedWebCorrection,
    expense_id: int,
    selected_id: str,
    payload: ExpenseCorrectionRequest,
    idempotency_key: str,
) -> CorrectionCommandOutcome:
    """Complete a previously claimed Web correction atomically."""

    if claimed.error is not None:
        return claimed.error
    if claimed.replayed:
        return CorrectionCommandOutcome()
    if claimed.claim is None:
        return CorrectionCommandOutcome(error=AppError("server_error").message, error_status=500)
    try:
        complete_correction_command(
            db,
            claim=claimed.claim,
            expense_id=expense_id,
            tenant_id=selected_id,
            payload=payload,
            actor_account_id=claimed.actor_account_id,
            actor_device_id=claimed.actor_device_id,
            idempotency_key=idempotency_key,
        )
    except AppError as exc:
        db.rollback()
        return _command_error(exc)
    return CorrectionCommandOutcome()
