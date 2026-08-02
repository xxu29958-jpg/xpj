"""CSV import service (v0.4-alpha3 slice 2 / PR17).

Parses a small CSV (≤500 rows) into a preview model and, on confirm,
writes them as ``status='pending'`` rows so the user can review them via
``/web/pending`` before they hit the ledger. No image, no OCR — purely
manual data entry shaped like the existing export schema.

Accepted columns (case-insensitive, BOM-aware):

* ``amount_yuan``, ``amount_cents`` or ``amount_home_major`` — one required.
  ``amount_yuan`` is the published legacy CSV compatibility column and always
  means CNY with two fraction digits. It is accepted only by CNY installations.
  Currency-aware producers must carry exact ``amount_cents`` plus an explicit
  matching ``home_currency_code``; ``amount_home_major`` is cross-checked using
  that currency's exponent.
* ``merchant`` — optional
* ``category`` — optional, defaults to ``"其他"``
* ``note`` — optional
* ``expense_time`` — optional ISO-8601, naive interpreted as Asia/Shanghai
* ``tags`` — optional
* ``source`` — optional, defaults to ``"CSV导入"``
* ``original_currency_code`` / ``original_amount_minor`` /
  ``exchange_rate_to_cny`` / ``exchange_rate_date`` — optional legacy
  metadata. Imported expenses still go through the backend FX resolver before
  a home amount is frozen.

Unknown columns are ignored. Each row is validated independently; rows
with errors are reported in the preview but skipped on import.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.models import Expense
from app.money_contract import MoneySign, ensure_optional_money_minor
from app.services.category_service import normalize_category
from app.services.currency_binding_service import assert_currency_binding_consistent
from app.services.exchange_rate_service import (
    BASE_CURRENCY_CODE,
    apply_currency_payload,
    home_currency_code,
    normalize_currency_code,
)
from app.services.import_money import (
    _parse_amount as _parse_amount,
)
from app.services.import_money import (
    _parse_optional_decimal as _parse_optional_decimal,
)
from app.services.import_money import (
    _parse_optional_int as _parse_optional_int,
)
from app.services.import_money import (
    validate_csv_headers as validate_csv_headers,
)
from app.services.spending_contract_service import fx_rate_date_for_expense_time
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import ensure_utc_assuming_local, now_utc

MAX_PREVIEW_ROWS = 500
DEFAULT_SOURCE = "CSV导入"


@dataclass
class ParsedRow:
    line_number: int
    amount_cents: int | None = None
    amount_display: str = ""
    original_currency_code: str = BASE_CURRENCY_CODE
    original_amount_minor: int | None = None
    exchange_rate_to_cny: Decimal | None = None
    exchange_rate_date: date | None = None
    exchange_rate_source: str | None = None
    merchant: str = ""
    category: str = "其他"
    note: str = ""
    expense_time: datetime | None = None
    expense_time_display: str = ""
    tags: str = ""
    source: str = DEFAULT_SOURCE
    error_code: str | None = None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.error is None


@dataclass
class CsvPreview:
    rows: list[ParsedRow] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.rows if r.is_valid)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if not r.is_valid)


def _parse_expense_time(raw: str, timezone_name: str | None = None) -> tuple[datetime | None, str, str | None, date | None]:
    text = raw.strip()
    if not text:
        return None, "", None, None
    try:
        # Accept "2025-01-02T03:04:05+08:00" or "2025-01-02 03:04:05".
        cleaned = text.replace("/", "-")
        if "T" not in cleaned and " " in cleaned:
            cleaned = cleaned.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None, text, "expense_time 不是合法的 ISO 时间", None
    resolved_timezone = (timezone_name or "").strip() or get_settings().ocr_default_timezone
    normalized_time = ensure_utc_assuming_local(parsed, resolved_timezone)
    return (
        normalized_time,
        text,
        None,
        fx_rate_date_for_expense_time(normalized_time, resolved_timezone),
    )


def _parse_optional_date(raw: str) -> tuple[date | None, str | None]:
    text = raw.strip()
    if not text:
        return None, None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None, "exchange_rate_date 不是合法日期"
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, "exchange_rate_date 不是合法日期"


def parse_csv_preview(content: str, timezone_name: str | None = None) -> CsvPreview:
    """Parse ``content`` into a preview structure.

    Caller is responsible for applying any size/encoding limits before
    calling this — we enforce :data:`MAX_PREVIEW_ROWS` and a defensive
    per-cell byte cap (``CSV_IMPORT_MAX_CELL_BYTES``). Total bytes / line
    counts must be enforced upstream (see ``create_csv_import_batch``).
    """
    max_cell_bytes = max(get_settings().csv_import_max_cell_bytes, 1)

    def _assert_cell(cell: str) -> None:
        if len(cell.encode("utf-8")) > max_cell_bytes:
            raise AppError(
                "invalid_request",
                f"CSV 单元格超过 {max_cell_bytes} 字节上限。",
                status_code=400,
            )
    text = content.lstrip("\ufeff")
    if not text.strip():
        raise AppError("invalid_request", "CSV 内容为空。", status_code=400)
    try:
        reader = csv.reader(StringIO(text))
        header_row = next(reader)
    except StopIteration as exc:
        raise AppError("invalid_request", "CSV 缺少表头。", status_code=400) from exc
    except csv.Error as exc:
        raise AppError("invalid_request", f"CSV 格式无效：{exc}", status_code=400) from exc
    for cell in header_row:
        _assert_cell(cell)
    headers = [h.strip().lstrip("\ufeff").lower() for h in header_row]
    validate_csv_headers(headers)
    parsed_home_currency = home_currency_code()
    preview = CsvPreview(headers=headers)
    try:
        for index, row in enumerate(reader, start=2):  # line 1 was the header
            if len(preview.rows) >= MAX_PREVIEW_ROWS:
                preview.truncated = True
                break
            if not any(cell.strip() for cell in row):
                continue
            for cell in row:
                _assert_cell(cell)
            preview.rows.append(
                parse_csv_row(
                    headers,
                    row,
                    line_number=index,
                    timezone_name=timezone_name,
                    home_currency=parsed_home_currency,
                )
            )
    except csv.Error as exc:
        raise AppError("invalid_request", f"CSV 格式无效：{exc}", status_code=400) from exc
    return preview


def _parse_csv_currency_code(
    raw: str,
    *,
    home_currency: str,
) -> tuple[str, str | None]:
    """Resolve ``original_currency_code`` cell → (code, error)."""
    cleaned = raw.strip()
    if not cleaned:
        return home_currency, None
    try:
        return normalize_currency_code(cleaned), None
    except AppError:
        return BASE_CURRENCY_CODE, "original_currency_code 暂不支持"


def _apply_csv_amount_currency_swap(
    *,
    amount_cents: int | None,
    amount_display: str,
    amount_error: str | None,
    original_amount_minor: int | None,
    original_currency_code: str,
    home_currency: str,
    has_original_fields: bool,
    explicit_amount_cents: bool,
    has_legacy_fx_snapshot: bool,
) -> tuple[int | None, str, str | None, int | None]:
    """Keep home/original units separate while preserving the released CSV shape.

    Older currency-aware exports used ``amount_cents`` for the original minor
    amount when the row also carried a complete FX snapshot.  Continue to
    accept that unambiguous shape, but reject a bare foreign currency plus
    ``amount_cents`` because it could otherwise be mistaken for a home amount.
    """
    is_foreign = has_original_fields and original_currency_code != home_currency
    if is_foreign and original_amount_minor is None:
        if (
            explicit_amount_cents
            and has_legacy_fx_snapshot
            and amount_cents is not None
        ):
            original_amount_minor = amount_cents
            amount_cents = None
            amount_display = ""
            amount_error = None
        else:
            amount_error = amount_error or "外币记录必须提供 original_amount_minor"
            amount_cents = None
            amount_display = ""
    if (
        is_foreign
        and original_amount_minor is not None
        and original_currency_code != home_currency
        and not explicit_amount_cents
    ):
        amount_cents = None
        amount_display = ""
        amount_error = None
    return amount_cents, amount_display, amount_error, original_amount_minor


def _authoritative_rate_for_currency(
    code: str,
    *,
    home_currency: str,
) -> tuple[Decimal | None, str | None]:
    if code == home_currency:
        return Decimal("1"), "base"
    return None, None


@dataclass(frozen=True)
class _CsvFxColumns:
    amount_cents: int | None
    amount_display: str
    amount_error_code: str | None
    amount_error: str | None
    original_currency_code: str
    original_amount_minor: int | None
    exchange_rate_date: date | None
    exchange_rate_to_cny: Decimal | None
    currency_error: str | None
    original_amount_error_code: str | None
    original_amount_error: str | None
    exchange_rate_error: str | None
    exchange_rate_date_error: str | None
    has_original_currency_fields: bool


def _parse_csv_fx_columns(
    cells: dict[str, str],
    *,
    amount_cents: int | None,
    amount_display: str,
    amount_error_code: str | None,
    amount_error: str | None,
    expense_rate_date: date | None,
    home_currency: str,
) -> _CsvFxColumns:
    original_currency_code, currency_error = _parse_csv_currency_code(
        cells.get("original_currency_code", ""),
        home_currency=home_currency,
    )
    (
        original_amount_minor,
        original_amount_error_code,
        original_amount_error,
    ) = _parse_optional_int(
        cells.get("original_amount_minor", ""),
        "original_amount_minor",
    )
    parsed_exchange_rate, exchange_rate_error = _parse_optional_decimal(
        cells.get("exchange_rate_to_cny", ""), "exchange_rate_to_cny"
    )
    exchange_rate_date, exchange_rate_date_error = _parse_optional_date(
        cells.get("exchange_rate_date", "")
    )
    if expense_rate_date is not None:
        exchange_rate_date = expense_rate_date
    has_original_currency_fields = any(
        cells.get(column, "").strip()
        for column in (
            "original_currency_code",
            "original_amount_minor",
            "exchange_rate_to_cny",
            "exchange_rate_date",
        )
    )
    previous_amount_error = amount_error
    amount_cents, amount_display, amount_error, original_amount_minor = (
        _apply_csv_amount_currency_swap(
            amount_cents=amount_cents,
            amount_display=amount_display,
            amount_error=amount_error,
            original_amount_minor=original_amount_minor,
            original_currency_code=original_currency_code,
            home_currency=home_currency,
            has_original_fields=has_original_currency_fields,
            explicit_amount_cents=bool(cells.get("amount_cents", "").strip()),
            has_legacy_fx_snapshot=(
                parsed_exchange_rate is not None
                and exchange_rate_date is not None
            ),
        )
    )
    if amount_error is not None and previous_amount_error is None:
        amount_error_code = "currency_snapshot_invalid"
    return _CsvFxColumns(
        amount_cents=amount_cents,
        amount_display=amount_display,
        amount_error_code=amount_error_code,
        amount_error=amount_error,
        original_currency_code=original_currency_code,
        original_amount_minor=original_amount_minor,
        exchange_rate_date=exchange_rate_date,
        exchange_rate_to_cny=parsed_exchange_rate,
        currency_error=currency_error,
        original_amount_error_code=original_amount_error_code,
        original_amount_error=original_amount_error,
        exchange_rate_error=exchange_rate_error,
        exchange_rate_date_error=exchange_rate_date_error,
        has_original_currency_fields=has_original_currency_fields,
    )


def parse_csv_row(
    headers: list[str],
    row: list[str],
    *,
    line_number: int,
    timezone_name: str | None = None,
    home_currency: str,
) -> ParsedRow:
    cells = dict(zip(headers, row + [""] * max(0, len(headers) - len(row)), strict=False))
    (
        amount_cents,
        amount_display,
        amount_error_code,
        amount_error,
    ) = _parse_amount(cells, home_currency=home_currency)
    expense_time, etime_display, etime_error, expense_rate_date = _parse_expense_time(
        cells.get("expense_time", ""), timezone_name=timezone_name
    )
    fx = _parse_csv_fx_columns(
        cells,
        amount_cents=amount_cents,
        amount_display=amount_display,
        amount_error_code=amount_error_code,
        amount_error=amount_error,
        expense_rate_date=expense_rate_date,
        home_currency=home_currency,
    )
    authoritative_rate, authoritative_rate_source = _authoritative_rate_for_currency(
        fx.original_currency_code,
        home_currency=home_currency,
    )
    error = (
        fx.currency_error
        or fx.original_amount_error
        or fx.exchange_rate_error
        or fx.exchange_rate_date_error
        or fx.amount_error
        or etime_error
    )
    error_code = (
        ("currency_not_supported" if fx.currency_error else None)
        or fx.original_amount_error_code
        or ("exchange_rate_invalid" if fx.exchange_rate_error else None)
        or (
            "exchange_rate_date_invalid"
            if fx.exchange_rate_date_error
            else None
        )
        or fx.amount_error_code
        or ("expense_time_invalid" if etime_error else None)
    )
    return ParsedRow(
        line_number=line_number,
        amount_cents=fx.amount_cents,
        amount_display=fx.amount_display,
        original_currency_code=fx.original_currency_code,
        original_amount_minor=fx.original_amount_minor if fx.has_original_currency_fields else fx.amount_cents,
        exchange_rate_to_cny=authoritative_rate,
        exchange_rate_date=fx.exchange_rate_date,
        exchange_rate_source=cells.get("exchange_rate_source", "").strip() or authoritative_rate_source,
        merchant=cells.get("merchant", "").strip(),
        category=normalize_category(cells.get("category", "")),
        note=cells.get("note", "").strip(),
        expense_time=expense_time,
        expense_time_display=etime_display,
        tags=normalize_tags(cells.get("tags", "")) or "",
        source=cells.get("source", "").strip() or DEFAULT_SOURCE,
        error_code=error_code,
        error=error,
    )


def import_rows(
    db: Session, *, tenant_id: str, rows: list[ParsedRow]
) -> int:
    """Insert valid rows as ``pending`` expenses. Returns the inserted count.

    Rows with ``error`` set are silently skipped — the caller already
    surfaced them in the preview UI.
    """
    for row in rows:
        if not row.is_valid:
            continue
        ensure_optional_money_minor(
            row.amount_cents,
            sign=MoneySign.NONNEGATIVE,
            label="csv_import.amount_cents",
        )
        ensure_optional_money_minor(
            row.original_amount_minor,
            sign=MoneySign.NONNEGATIVE,
            label="csv_import.original_amount_minor",
        )
    # Legacy import is one transaction; the database fence remains the final guard.
    assert_currency_binding_consistent(db, home_currency_code())
    inserted = 0
    now = now_utc()
    created: list[Expense] = []
    for row in rows:
        if not row.is_valid or (row.amount_cents is None and row.original_amount_minor is None):
            continue
        expense = Expense(
            tenant_id=tenant_id,
            amount_cents=None,
            merchant=row.merchant or None,
            category=row.category or "其他",
            note=row.note or "",
            source=row.source or DEFAULT_SOURCE,
            tags=normalize_tags(row.tags),
            expense_time=row.expense_time,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        apply_currency_payload(
            db,
            tenant_id=tenant_id,
            expense=expense,
            payload=row,
            amount_was_explicit=row.original_currency_code == home_currency_code() and row.amount_cents is not None,
        )
        db.add(expense)
        created.append(expense)
        inserted += 1
    if inserted:
        db.flush()
        for expense in created:
            sync_expense_tags(db, expense)
        db.commit()
    return inserted
