"""Interpret native CSV event provenance without creating financial facts."""

from __future__ import annotations

import re
from datetime import date
from uuid import UUID

from app.errors import AppError
from app.money_contract import MONEY_AGGREGATE_MAX
from app.schemas._accounting_time import AccountingTimeInput, AccountingTimeSnapshot
from app.services.accounting_time_service import resolve_accounting_time

_EVENT_COLUMNS = (
    "entry_kind", "offset_kind", "root_expense_id", "root_expense_public_id",
    "source_event_public_id", "source_root_public_id", "accounting_date",
    "stream_date", "stream_amount_cents", "lineage_status", "lineage_home_net_cents",
)
_LINEAGE_STATUSES = {"confirmed", "partially_refunded", "fully_refunded", "reversed"}
NATIVE_CSV_INPUT_COLUMNS = (
    "id", "public_id", "amount_cents", "amount_yuan", "amount_home_major", "home_currency_code",
    "original_currency_code", "original_amount_minor", "exchange_rate_to_cny", "exchange_rate_date",
    "exchange_rate_source", "merchant", "category", "note", "source", "expense_time", "confirmed_at",
    "tags", "value_score", "regret_score", "accounting_time", *_EVENT_COLUMNS,
)


def has_financial_event(cells: dict[str, str]) -> bool:
    """Blank event cells in a mixed error download remain ordinary CSV rows."""
    return any(cells.get(name, "").strip() for name in _EVENT_COLUMNS)


def _provenance_id(cells: dict[str, str], name: str, alias: str, errors: list[str]) -> str | None:
    raw, alternate = cells.get(name, "").strip(), cells.get(alias, "").strip()
    if raw and alternate and raw != alternate:
        errors.append(f"{name} 与 {alias} 不一致")
    value = raw or alternate
    try:
        return str(UUID(value))
    except ValueError:
        errors.append(f"{name} 必须是有效的源事件 UUID")
        return None


def _event_date(cells: dict[str, str], errors: list[str]) -> date | None:
    raw, alternate = cells.get("stream_date", "").strip(), cells.get("accounting_date", "").strip()
    if raw and alternate and raw != alternate:
        errors.append("stream_date 与 accounting_date 不一致")
    value = raw or alternate
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError:
        errors.append("stream_date 必须是 YYYY-MM-DD 日期")
        return None


def _event_amount(cells: dict[str, str], name: str, errors: list[str]) -> int | None:
    raw = cells.get(name, "")
    if len(raw) <= len(str(-MONEY_AGGREGATE_MAX)) and re.fullmatch(r"0|-?[1-9][0-9]*", raw):
        value = int(raw)
        if abs(value) <= MONEY_AGGREGATE_MAX:
            return value
    errors.append(f"{name} 必须是可支持范围内的规范整数")
    return None


def _event_identity_error(fields: dict[str, object], amount_cents: int | None) -> str | None:
    kind, offset_kind = fields["entry_kind"], fields["offset_kind"]
    event_id, root_id = fields["source_event_public_id"], fields["source_root_public_id"]
    if kind not in {"expense", "offset"}:
        return "entry_kind 必须明确为 expense 或 offset"
    if kind == "expense":
        if offset_kind or event_id != root_id:
            return "根单的 offset_kind 必须为空，事件 UUID 必须等于原单 UUID"
    elif offset_kind not in {"refund", "chargeback", "reversal"} or event_id == root_id:
        return "offset 必须明确退款或冲正类型，并具有独立于原单的事件 UUID"
    if kind == "offset" and (amount_cents is None or amount_cents <= 0):
        return "offset 必须保留正数原始金额，零贡献不等于零金额"
    return None


def _event_shape_error(fields: dict[str, object], amount_cents: int | None) -> str | None:
    identity_error = _event_identity_error(fields, amount_cents)
    if identity_error:
        return identity_error
    kind, offset_kind = fields["entry_kind"], fields["offset_kind"]
    status = fields["lineage_status"]
    if status not in _LINEAGE_STATUSES:
        return "lineage_status 缺失或未知"
    expected = amount_cents
    if kind == "offset":
        expected = -amount_cents if amount_cents is not None else None
    if status == "reversed" or offset_kind == "reversal":
        expected = 0
    if fields["stream_amount_cents"] != expected:
        return "stream_amount_cents 与事件类型、原始金额或冲正状态不一致"
    if offset_kind == "reversal" and status != "reversed":
        return "reversal 必须具有 reversed 关联状态"
    if kind == "offset" and offset_kind != "reversal" and status not in {"partially_refunded", "fully_refunded"}:
        return "退款或退单的关联状态不一致"
    return None


def parse_financial_event(cells: dict[str, str], *, amount_cents: int | None) -> tuple[dict[str, object], str | None]:
    """Keep source IDs and signed contribution distinct from the gross amount."""
    errors: list[str] = []
    fields = {
        "entry_kind": cells.get("entry_kind", "").strip(),
        "offset_kind": cells.get("offset_kind", "").strip() or None,
        "source_event_public_id": _provenance_id(cells, "public_id", "source_event_public_id", errors),
        "source_root_public_id": _provenance_id(cells, "root_expense_public_id", "source_root_public_id", errors),
        "accounting_date": _event_date(cells, errors),
        "stream_amount_cents": _event_amount(cells, "stream_amount_cents", errors),
        "lineage_status": cells.get("lineage_status", "").strip() or None,
        "lineage_home_net_cents": _event_amount(cells, "lineage_home_net_cents", errors),
    }
    shape_error = _event_shape_error(fields, amount_cents)
    if shape_error:
        errors.append(shape_error)
    if fields["lineage_status"] == "reversed" and fields["lineage_home_net_cents"] != 0:
        errors.append("reversed 的 lineage_home_net_cents 必须为零")
    time_error = _native_time_error(cells, fields)
    if time_error:
        errors.append(time_error)
    if fields["entry_kind"] not in {"expense", "offset"}:
        fields["entry_kind"] = "invalid"
    if fields["offset_kind"] not in {"refund", "chargeback", "reversal"}:
        fields["offset_kind"] = None
    if fields["lineage_status"] not in _LINEAGE_STATUSES:
        fields["lineage_status"] = None
    fields["event_input"] = {name: cells[name] for name in NATIVE_CSV_INPUT_COLUMNS if name in cells}
    return fields, errors[0] if errors else None


def _native_time_error(cells: dict[str, str], fields: dict[str, object]) -> str | None:
    try:
        snapshot = native_accounting_time(cells)
    except (ValueError, AppError):
        return "accounting_time 的原始日期、精度或时区证据不一致"
    if snapshot is None:
        return None
    if snapshot.accounting_date != fields["accounting_date"]:
        return "accounting_time 与 stream_date 不一致"
    if fields["entry_kind"] == "offset" and snapshot.precision != "date_only":
        return "offset 必须保留仅日期精度"
    return None


def native_accounting_time(cells: dict[str, str]) -> AccountingTimeSnapshot | None:
    """Read an explicit source snapshot; its revision is evidence, never a target FK."""
    raw = cells.get("accounting_time", "").strip()
    if not raw:
        return None
    snapshot = AccountingTimeSnapshot.model_validate_json(raw)
    if snapshot.precision == "date_only" and (snapshot.instant_utc is not None or snapshot.source_utc_offset_seconds is not None):
        raise ValueError("date-only source carries an instant")
    if snapshot.precision == "instant":
        value = AccountingTimeInput(**snapshot.model_dump(exclude={"basis", "precision"}), precision="instant")
        resolve_accounting_time(value, ledger_timezone=snapshot.source_timezone or "UTC",
            calendar_revision=snapshot.calendar_revision)
    return snapshot


def native_money_fields_error(cells: dict[str, str]) -> str | None:
    required = ("amount_cents", "home_currency_code", "original_currency_code", "original_amount_minor")
    missing = [name for name in required if not cells.get(name, "").strip()]
    if missing:
        return f"原生事件缺少冻结金额字段：{', '.join(missing)}"
    # Historical exports may retain only part of the quote. Keep each known
    # value; a new fact needs explicit completion through the saved review.
    if len(cells.get("exchange_rate_source", "").strip()) > 32:
        return "exchange_rate_source 超出可保存的来源长度"
    return None
