"""CSV import service (v0.4-alpha3 slice 2 / PR17).

Parses a small CSV (≤500 rows) into a preview model and, on confirm,
writes them as ``status='pending'`` rows so the user can review them via
``/web/pending`` before they hit the ledger. No image, no OCR — purely
manual data entry shaped like the existing export schema.

Accepted columns (case-insensitive, BOM-aware):

* ``amount_yuan`` *or* ``amount_cents`` — required, must parse as number
* ``merchant`` — optional
* ``category`` — optional, defaults to ``"其他"``
* ``note`` — optional
* ``expense_time`` — optional ISO-8601, naive interpreted as Asia/Shanghai
* ``tags`` — optional
* ``source`` — optional, defaults to ``"CSV导入"``

Unknown columns are ignored. Each row is validated independently; rows
with errors are reported in the preview but skipped on import.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense
from app.services.category_service import normalize_category
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import now_utc


MAX_PREVIEW_ROWS = 500
DEFAULT_SOURCE = "CSV导入"


@dataclass
class ParsedRow:
    line_number: int
    amount_cents: int | None = None
    amount_display: str = ""
    merchant: str = ""
    category: str = "其他"
    note: str = ""
    expense_time: datetime | None = None
    expense_time_display: str = ""
    tags: str = ""
    source: str = DEFAULT_SOURCE
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


def _parse_amount(raw_yuan: str, raw_cents: str) -> tuple[int | None, str, str | None]:
    if raw_cents.strip():
        try:
            cents = int(raw_cents.strip())
        except ValueError:
            return None, raw_cents, "amount_cents 不是整数"
        if cents < 0:
            return None, raw_cents, "金额不能为负"
        yuan = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
        return cents, f"{yuan}", None
    text = raw_yuan.strip()
    if not text:
        return None, "", "缺少 amount_yuan 或 amount_cents"
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, text, "amount_yuan 不是合法数字"
    if amount < 0:
        return None, text, "金额不能为负"
    cents = int((amount * Decimal(100)).quantize(Decimal("1")))
    return cents, str(amount.quantize(Decimal("0.01"))), None


def _parse_expense_time(raw: str) -> tuple[datetime | None, str, str | None]:
    text = raw.strip()
    if not text:
        return None, "", None
    try:
        # Accept "2025-01-02T03:04:05+08:00" or "2025-01-02 03:04:05" (naive => UTC).
        cleaned = text.replace("/", "-")
        if "T" not in cleaned and " " in cleaned:
            cleaned = cleaned.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None, text, "expense_time 不是合法的 ISO 时间"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, text, None


def parse_csv_preview(content: str) -> CsvPreview:
    """Parse ``content`` into a preview structure.

    Caller is responsible for applying any size/encoding limits before
    calling this — we only enforce :data:`MAX_PREVIEW_ROWS`.
    """
    text = content.lstrip("\ufeff")
    if not text.strip():
        raise AppError("invalid_request", "CSV 内容为空。", status_code=400)
    reader = csv.reader(StringIO(text))
    try:
        header_row = next(reader)
    except StopIteration:
        raise AppError("invalid_request", "CSV 缺少表头。", status_code=400)
    headers = [h.strip().lstrip("\ufeff").lower() for h in header_row]
    if not any(h in {"amount_yuan", "amount_cents"} for h in headers):
        raise AppError(
            "invalid_request",
            "CSV 必须包含 amount_yuan 或 amount_cents 列。",
            status_code=400,
        )
    preview = CsvPreview(headers=headers)
    for index, row in enumerate(reader, start=2):  # line 1 was the header
        if len(preview.rows) >= MAX_PREVIEW_ROWS:
            preview.truncated = True
            break
        if not any(cell.strip() for cell in row):
            continue
        preview.rows.append(parse_csv_row(headers, row, line_number=index))
    return preview


def parse_csv_row(headers: list[str], row: list[str], *, line_number: int) -> ParsedRow:
    cells = dict(zip(headers, row + [""] * max(0, len(headers) - len(row)), strict=False))
    amount_cents, amount_display, amount_error = _parse_amount(
        cells.get("amount_yuan", ""), cells.get("amount_cents", "")
    )
    expense_time, etime_display, etime_error = _parse_expense_time(
        cells.get("expense_time", "")
    )
    category = normalize_category(cells.get("category", ""))
    merchant = cells.get("merchant", "").strip()
    note = cells.get("note", "").strip()
    tags = cells.get("tags", "").strip()
    source = cells.get("source", "").strip() or DEFAULT_SOURCE
    error = amount_error or etime_error
    return ParsedRow(
        line_number=line_number,
        amount_cents=amount_cents,
        amount_display=amount_display,
        merchant=merchant,
        category=category,
        note=note,
        expense_time=expense_time,
        expense_time_display=etime_display,
        tags=tags,
        source=source,
        error=error,
    )


def import_rows(
    db: Session, *, tenant_id: str, rows: list[ParsedRow]
) -> int:
    """Insert valid rows as ``pending`` expenses. Returns the inserted count.

    Rows with ``error`` set are silently skipped — the caller already
    surfaced them in the preview UI.
    """
    inserted = 0
    now = now_utc()
    created: list[Expense] = []
    for row in rows:
        if not row.is_valid or row.amount_cents is None:
            continue
        expense = Expense(
            tenant_id=tenant_id,
            amount_cents=row.amount_cents,
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
        db.add(expense)
        created.append(expense)
        inserted += 1
    if inserted:
        db.flush()
        for expense in created:
            sync_expense_tags(db, expense)
        db.commit()
    return inserted
