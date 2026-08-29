"""Correction 表单输入解析 + current-diff（A1 Web 适配层责任之一）。

把浏览器的一次更正 POST（标量 + 明细行 + 拆账行 + reason）翻译成一个
``ExpenseCorrectionRequest``，或一个带行级/字段级错误的失败 outcome。

责任边界：
- 标量解析与「只带真实变化字段」复用 pending 编辑的
  ``prepare_web_expense_form``（同一语义，两个真实消费者）；
- 明细/拆账行解析复用 ``_web_expense_rows`` 的 replace payload 构造器；
- 「段落是否进入更正意图」的 diff 是本模块独有的更正语义 ——
  与当前事实逐行比对，未触碰的段落不重写（避免「只想改商家」
  误覆盖整段明细/OCR 草稿态）。

不做：命令执行/幂等/OCC（_web_correction_command）、页面渲染
（_web_correction_page）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fastapi import Depends, Form, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_edit_command import prepare_web_expense_form
from app.routes._web_expense_form import web_form_error_status
from app.routes._web_expense_rows import (
    attach_form_row_error,
    item_replace_payload,
    split_replace_payload,
    submitted_item_form_rows,
    submitted_split_form_rows,
)
from app.schemas import (
    ExpenseCorrectionRequest,
    ExpenseItemRequest,
    ExpenseItemResponse,
    ExpenseSplitRequest,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.expense_split_service import list_expense_splits
from app.services.receipt_item_service import list_expense_items

REASON_REQUIRED_MSG = "请说明这次更正的原因。"
NO_CHANGES_MSG = "没有检测到需要保存的更正。"


@dataclass(frozen=True)
class CorrectionFormData:
    """一次 corrections POST 的原始表单字段（薄路由只做这一层打包）。"""

    reason: str
    amount_yuan: str | None
    original_currency: str
    merchant: str | None
    category: str
    note: str
    expense_time: str | None
    expense_time_present: bool
    tags: str
    value_score: str | None
    value_score_present: bool
    regret_score: str | None
    regret_score_present: bool
    item_name: list[str]
    item_kind: list[str]
    item_quantity: list[str]
    item_unit_price_yuan: list[str]
    item_amount_yuan: list[str]
    item_category: list[str]
    split_member_id: list[str]
    split_amount_yuan: list[str]
    split_note: list[str]
    expected_row_version: str
    idempotency_key: str


@dataclass
class CorrectionParseOutcome:
    """解析结果：成功时 ``payload`` 为可执行命令；失败时带渲染所需全部状态。"""

    form_values: dict[str, str]
    item_form_rows: list[dict]
    split_form_rows: list[dict]
    payload: ExpenseCorrectionRequest | None = None
    error: str | None = None
    error_status: int = 422
    field_errors: dict[str, str] = field(default_factory=dict)


def web_correction_idempotency_body(form: CorrectionFormData) -> dict[str, object]:
    """Stable browser intent fingerprint, independent of the later fact state."""

    submitted = asdict(form)
    submitted.pop("expected_row_version")
    submitted.pop("idempotency_key")
    return {"web_form": submitted}


async def _submitted_form_field_names(request: Request) -> frozenset[str]:
    """Keep absent and explicitly blank correction fields distinguishable."""

    return frozenset((await request.form()).keys())


def correction_form_data(
    reason: str = Form(default=""),
    amount_yuan: str | None = Form(default=None),
    original_currency: str = Form(default=""),
    merchant: str | None = Form(default=None),
    category: str = Form(default=""),
    note: str = Form(default=""),
    expense_time: str | None = Form(default=None),
    tags: str = Form(default=""),
    value_score: str | None = Form(default=None),
    regret_score: str | None = Form(default=None),
    item_name: list[str] = Form(default=[]),
    item_kind: list[str] = Form(default=[]),
    item_quantity: list[str] = Form(default=[]),
    item_unit_price_yuan: list[str] = Form(default=[]),
    item_amount_yuan: list[str] = Form(default=[]),
    item_category: list[str] = Form(default=[]),
    split_member_id: list[str] = Form(default=[]),
    split_amount_yuan: list[str] = Form(default=[]),
    split_note: list[str] = Form(default=[]),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    submitted_fields: frozenset[str] = Depends(_submitted_form_field_names),
) -> CorrectionFormData:
    """Bind FastAPI form fields without making the HTTP route a giant parser."""

    return CorrectionFormData(
        reason=reason,
        amount_yuan=amount_yuan,
        original_currency=original_currency,
        merchant=merchant,
        category=category,
        note=note,
        expense_time=expense_time,
        expense_time_present="expense_time" in submitted_fields,
        tags=tags,
        value_score=value_score,
        value_score_present="value_score" in submitted_fields,
        regret_score=regret_score,
        regret_score_present="regret_score" in submitted_fields,
        item_name=item_name,
        item_kind=item_kind,
        item_quantity=item_quantity,
        item_unit_price_yuan=item_unit_price_yuan,
        item_amount_yuan=item_amount_yuan,
        item_category=item_category,
        split_member_id=split_member_id,
        split_amount_yuan=split_amount_yuan,
        split_note=split_note,
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
    )


def _normalized_items(items: list[ExpenseItemRequest] | list[ExpenseItemResponse]) -> list[tuple]:
    return [
        (
            item.kind,
            (item.name or "").strip(),
            (item.quantity_text or "").strip() or None,
            item.unit_price_cents,
            item.amount_cents,
            (item.category or "").strip() or None,
        )
        for item in items
    ]


def _submitted_item_indexes(form: CorrectionFormData) -> list[int]:
    fields = (
        form.item_name,
        form.item_quantity,
        form.item_unit_price_yuan,
        form.item_amount_yuan,
        form.item_category,
    )
    size = max(*(len(values) for values in fields), 0)
    return [
        index
        for index in range(size)
        if any(index < len(values) and values[index].strip() for values in fields)
    ]


def _preserve_item_provenance(
    candidate: list[ExpenseItemRequest],
    current: list[ExpenseItemResponse],
    form: CorrectionFormData,
) -> list[ExpenseItemRequest]:
    preserved: list[ExpenseItemRequest] = []
    for item, source_index in zip(candidate, _submitted_item_indexes(form), strict=True):
        if source_index >= len(current):
            preserved.append(item)
            continue
        source = current[source_index]
        preserved.append(
            item.model_copy(
                update={"raw_text": source.raw_text, "confidence": source.confidence}
            )
        )
    return preserved


def _normalized_splits(splits: list[ExpenseSplitRequest]) -> list[tuple]:
    return [(split.member_id, split.amount_cents, (split.note or "").strip() or None) for split in splits]


def _current_splits_normalized(db: Session, expense_id: int, ledger_id: str) -> list[tuple]:
    return [
        (split.member_id, split.amount_cents, (split.note or "").strip() or None)
        for split in list_expense_splits(db, expense_id, ledger_id).splits
    ]


def _form_values_from(form: CorrectionFormData) -> dict[str, str]:
    values = {
        "reason": form.reason,
        "expected_row_version": form.expected_row_version,
        "idempotency_key": form.idempotency_key,
        "amount_yuan": form.amount_yuan,
        "original_currency": form.original_currency,
        "merchant": form.merchant,
        "category": form.category,
        "note": form.note,
        "tags": form.tags,
        "expense_time": (form.expense_time or "") if form.expense_time_present else None,
        "value_score": (form.value_score or "") if form.value_score_present else None,
        "regret_score": (form.regret_score or "") if form.regret_score_present else None,
    }
    return {key: value for key, value in values.items() if value is not None}


def _score_change(
    raw: str | None,
    current: int | None,
    *,
    present: bool,
) -> tuple[bool, int | None, str | None]:
    """Parse one optional score while preserving absent/value/clear semantics."""

    if not present:
        return False, None, None
    cleaned = (raw or "").strip()
    if not cleaned:
        return current is not None, None, None
    try:
        candidate = int(cleaned)
    except ValueError:
        return False, None, "评分只能选择 1 到 5，或清空评分。"
    if candidate not in range(1, 6):
        return False, None, "评分只能选择 1 到 5，或清空评分。"
    return candidate != current, candidate, None


def _correction_outcome(form: CorrectionFormData) -> CorrectionParseOutcome:
    return CorrectionParseOutcome(
        form_values=_form_values_from(form),
        item_form_rows=submitted_item_form_rows(
            item_name=form.item_name,
            item_kind=form.item_kind,
            item_quantity=form.item_quantity,
            item_unit_price_yuan=form.item_unit_price_yuan,
            item_amount_yuan=form.item_amount_yuan,
            item_category=form.item_category,
        ),
        split_form_rows=submitted_split_form_rows(
            split_member_id=form.split_member_id,
            split_amount_yuan=form.split_amount_yuan,
            split_note=form.split_note,
        ),
    )


def _reason_or_error(form: CorrectionFormData, outcome: CorrectionParseOutcome) -> str | None:
    reason = (form.reason or "").strip()
    if not reason:
        outcome.error = REASON_REQUIRED_MSG
        outcome.field_errors = {"reason": REASON_REQUIRED_MSG}
        return None
    if len(reason) > 500:
        outcome.error = "更正原因最多 500 个字符。"
        outcome.field_errors = {"reason": outcome.error}
        return None
    return reason


def _scalar_changes(
    db: Session,
    *,
    expense,
    selected_id: str,
    form: CorrectionFormData,
    outcome: CorrectionParseOutcome,
) -> tuple[dict[str, object], int] | None:
    update_payload, prepared = prepare_web_expense_form(
        db,
        expense_id=expense.id,
        selected_ledger_id=selected_id,
        expected_row_version=form.expected_row_version,
        idempotency_key=form.idempotency_key,
        amount_yuan=form.amount_yuan,
        original_currency=form.original_currency,
        merchant=form.merchant,
        category=form.category,
        note=form.note,
        tags=form.tags,
        expense_time=form.expense_time,
        allow_currency_change=True,
    )
    if update_payload is None:
        outcome.error = prepared.error or "提交参数不正确，请检查后重试。"
        outcome.error_status = prepared.error_status
        outcome.field_errors = prepared.field_errors or {}
        return None
    changes = update_payload.model_dump(exclude_unset=True, exclude={"expected_row_version"})
    if form.expense_time_present and not (form.expense_time or "").strip() and expense.expense_time is not None:
        changes["expense_time"] = None
    for field_name, raw, current, present in (
        ("value_score", form.value_score, expense.value_score, form.value_score_present),
        ("regret_score", form.regret_score, expense.regret_score, form.regret_score_present),
    ):
        changed, candidate, score_error = _score_change(raw, current, present=present)
        if score_error is not None:
            outcome.error = score_error
            outcome.field_errors = {field_name: score_error}
            return None
        if changed:
            changes[field_name] = candidate
    return changes, update_payload.expected_row_version


def _item_changes(
    db: Session,
    *,
    expense,
    selected_id: str,
    form: CorrectionFormData,
    row_version: int,
    currency: str,
    outcome: CorrectionParseOutcome,
) -> tuple[list[ExpenseItemRequest], bool] | None:
    try:
        candidate = item_replace_payload(
            currency_code=currency,
            expected_row_version=row_version,
            item_name=form.item_name,
            item_kind=form.item_kind,
            item_quantity=form.item_quantity,
            item_unit_price_yuan=form.item_unit_price_yuan,
            item_amount_yuan=form.item_amount_yuan,
            item_category=form.item_category,
        ).items
    except AppError as exc:
        attach_form_row_error(outcome.item_form_rows, exc)
        outcome.error = exc.message
        outcome.error_status = web_form_error_status(exc)
        return None
    current = list_expense_items(db, expense.id, selected_id).items
    candidate = _preserve_item_provenance(candidate, current, form)
    return candidate, _normalized_items(candidate) != _normalized_items(current)


def _split_changes(
    db: Session,
    *,
    expense,
    selected_id: str,
    form: CorrectionFormData,
    row_version: int,
    currency: str,
    outcome: CorrectionParseOutcome,
) -> tuple[list[ExpenseSplitRequest], bool] | None:
    try:
        candidate = split_replace_payload(
            currency_code=currency,
            expected_row_version=row_version,
            split_member_id=form.split_member_id,
            split_amount_yuan=form.split_amount_yuan,
            split_note=form.split_note,
        ).splits
    except AppError as exc:
        attach_form_row_error(outcome.split_form_rows, exc)
        outcome.error = exc.message
        outcome.error_status = web_form_error_status(exc)
        return None
    current = _current_splits_normalized(db, expense.id, selected_id)
    return candidate, _normalized_splits(candidate) != current


def parse_correction_form(
    db: Session,
    *,
    expense,
    selected_id: str,
    form: CorrectionFormData,
) -> CorrectionParseOutcome:
    """Validate + diff one correction POST against the current fact snapshot."""

    outcome = _correction_outcome(form)
    reason = _reason_or_error(form, outcome)
    if reason is None:
        return outcome
    scalar_result = _scalar_changes(db, expense=expense, selected_id=selected_id, form=form, outcome=outcome)
    if scalar_result is None:
        return outcome
    scalar_changes, row_version = scalar_result
    currency = expense.home_currency_code or require_runtime_home_currency_code(db)
    item_result = _item_changes(
        db,
        expense=expense,
        selected_id=selected_id,
        form=form,
        row_version=row_version,
        currency=currency,
        outcome=outcome,
    )
    if outcome.error is not None:
        return outcome
    assert item_result is not None
    split_result = _split_changes(
        db,
        expense=expense,
        selected_id=selected_id,
        form=form,
        row_version=row_version,
        currency=currency,
        outcome=outcome,
    )
    if outcome.error is not None:
        return outcome
    assert split_result is not None
    items, items_changed = item_result
    splits, splits_changed = split_result
    items_payload = items if items_changed else None
    splits_payload = splits if splits_changed else None
    if not scalar_changes and items_payload is None and splits_payload is None:
        outcome.error = NO_CHANGES_MSG
        return outcome

    try:
        outcome.payload = ExpenseCorrectionRequest(
            **scalar_changes,
            expected_row_version=row_version,
            reason=reason,
            items=items_payload,
            splits=splits_payload,
        )
    except ValidationError:
        outcome.error = "提交参数不正确，请检查后重试。"
    return outcome
