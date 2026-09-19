"""Raw native-form adaptation; accounting-time validation remains in the kernel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request
from pydantic import ValidationError

from app.errors import AppError
from app.schemas._accounting_time import AccountingTimeInput
from app.services.time_service import ensure_utc, resolve_local_datetime, strict_zone

TIME_FIELDS = (
    "time_precision", "calendar_revision", "user_local_date", "source_timezone",
    "source_utc_offset_seconds", "accounting_date",
)


async def accounting_time_form_fields(request: Request) -> dict[str, str] | None:
    raw = await request.form()
    if not any(name in raw for name in TIME_FIELDS):
        return None
    return {name: str(raw[name]) for name in TIME_FIELDS if name in raw}


def parse_web_accounting_time(
    wall_time: str | None, fields: dict[str, str] | None,
) -> AccountingTimeInput | None:
    if fields is None:
        return None
    try:
        zone = fields.get("source_timezone", "").strip() or None
        offset_text = fields.get("source_utc_offset_seconds", "").strip()
        offset = int(offset_text) if offset_text else None
        precision = fields.get("time_precision", "")
        instant = None
        local_date = fields.get("user_local_date", "")
        if precision == "instant":
            wall = datetime.fromisoformat((wall_time or "").replace("Z", "+00:00"))
            local_date = wall.date()
            if zone:
                instant = resolve_local_datetime(wall, zone, utc_offset_seconds=offset)
                offset = int(instant.astimezone(strict_zone(zone)).utcoffset().total_seconds())
            elif offset is not None:
                if wall.utcoffset() is not None and wall.utcoffset() != timedelta(seconds=offset):
                    raise ValueError("conflicting explicit offsets")
                instant = ensure_utc(wall.replace(tzinfo=timezone(timedelta(seconds=offset))))
            else:
                raise ValueError("missing source timezone or offset")
        return AccountingTimeInput(
            precision=precision, calendar_revision=int(fields.get("calendar_revision", "")),
            user_local_date=local_date, instant_utc=instant, source_timezone=zone,
            source_utc_offset_seconds=offset if precision == "instant" else None,
            accounting_date=fields.get("accounting_date", "").strip() or None,
        )
    except (ValueError, ValidationError) as exc:
        raise AppError("accounting_time_invalid", "请检查发生日期、时间、时区与日历版本。", status_code=422) from exc


def time_form_values(expense, rule) -> dict[str, str]:
    """Present known source evidence, preserving seconds and the selected fold."""
    if rule is None:
        raise AppError("accounting_calendar_required", "请先采用账本日历，再填写发生日期。", status_code=409)
    instant = ensure_utc(getattr(expense, "expense_time", None))
    source_zone = getattr(expense, "source_timezone", None)
    offset = getattr(expense, "source_utc_offset_seconds", None)
    zone = source_zone or (rule.timezone_name if offset is None else None)
    wall = None
    if instant is not None:
        display_zone = strict_zone(zone) if zone else timezone(timedelta(seconds=offset))
        wall = instant.astimezone(display_zone)
        offset = int(wall.utcoffset().total_seconds())
    date = getattr(expense, "user_local_date", None) or (wall.date() if wall else None)
    accounting_date = getattr(expense, "accounting_date", None)
    return {
        "time_precision": "instant" if instant else "date_only",
        "calendar_revision": str(getattr(expense, "calendar_revision", None) or rule.revision),
        "user_local_date": date.isoformat() if date else "",
        "source_timezone": zone or "",
        "source_utc_offset_seconds": str(offset) if instant and offset is not None else "",
        "accounting_date": (accounting_date.isoformat()
            if accounting_date and getattr(expense, "accounting_date_basis", None) == "user_selected" else ""),
        "wall_time": wall.replace(tzinfo=None).isoformat() if wall else "",
    }


def time_form_projection(values: dict[str, str]) -> dict:
    """Offer both repeated wall-clock choices without changing retained input."""
    options = []
    zone = values.get("source_timezone", "")
    raw = values.get("wall_time", "")
    if zone and raw:
        try:
            resolve_local_datetime(datetime.fromisoformat(raw), zone)
        except AppError as exc:
            if exc.error == "local_time_ambiguous":
                options = (exc.details or {}).get("utc_offset_seconds_options", [])
        except ValueError:
            pass
    return {**values, "offset_options": options}


def changed_time_input(expense, rule, wall_time: str | None, fields: dict[str, str]):
    # Native pending edits have always treated a blank clock as unchanged;
    # correction's explicit-null adapter owns clearing a known clock. A blank
    # date-only clock must still carry its real date through the value object.
    if fields.get("time_precision") == "instant" and not (wall_time or "").strip():
        return None
    baseline = time_form_values(expense, rule)
    try:
        wall = datetime.fromisoformat(wall_time) if wall_time else None
        before = datetime.fromisoformat(baseline["wall_time"]) if baseline["wall_time"] else None
    except ValueError:
        return parse_web_accounting_time(wall_time, fields)
    if wall == before and all(fields.get(name, "") == baseline[name] for name in TIME_FIELDS):
        return None
    return parse_web_accounting_time(wall_time, fields)


def known_instant_label(expense) -> str:
    instant = ensure_utc(getattr(expense, "expense_time", None))
    if instant is None:
        return ""
    zone = getattr(expense, "source_timezone", None)
    offset = getattr(expense, "source_utc_offset_seconds", None)
    if zone:
        return f"{instant.astimezone(strict_zone(zone)).isoformat(sep=' ')} ({zone})"
    if offset is not None:
        instant = instant.astimezone(timezone(timedelta(seconds=offset)))
    return instant.isoformat(sep=" ")


def accounting_snapshot_label(value: dict) -> str:
    precision = {"instant": "已知时刻", "date_only": "只有日期", "unknown": "原始时间证据未知"}
    parts = [f"账务日期 {value.get('accounting_date') or '待核对'}",
        precision.get(value.get("precision"), "原始时间证据未知")]
    if value.get("user_local_date"):
        parts.append(f"发生日期 {value['user_local_date']}")
    if value.get("instant_utc"):
        parts.append(str(value["instant_utc"]))
    if (value.get("basis") or "").startswith("legacy_"):
        parts.append("按初始账本日历推定")
    return " · ".join(parts)
