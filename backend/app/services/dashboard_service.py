from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import DashboardCardPreference
from app.schemas import DashboardCardsResponse, DashboardCardsUpdateRequest
from app.services.time_service import now_utc

DashboardSurface = str


@dataclass(frozen=True)
class DashboardCardDefinition:
    key: str
    title: str


DEFAULT_DASHBOARD_CARDS: dict[DashboardSurface, tuple[DashboardCardDefinition, ...]] = {
    "android": (
        DashboardCardDefinition("monthly_spend", "本月支出"),
        DashboardCardDefinition("budget", "预算"),
        DashboardCardDefinition("reports", "趋势报表"),
        DashboardCardDefinition("goals", "目标"),
        DashboardCardDefinition("recurring", "固定支出"),
        DashboardCardDefinition("pending", "待确认"),
        DashboardCardDefinition("recent_uploads", "最近上传"),
    ),
    "web": (
        DashboardCardDefinition("monthly_spend", "本月支出"),
        DashboardCardDefinition("budget", "预算"),
        DashboardCardDefinition("reports", "报表"),
        DashboardCardDefinition("goals", "目标"),
        DashboardCardDefinition("recurring", "固定支出"),
        DashboardCardDefinition("pending", "待确认"),
        DashboardCardDefinition("recent_uploads", "最近上传"),
        DashboardCardDefinition("backup_status", "备份状态"),
        DashboardCardDefinition("device_status", "设备状态"),
    ),
}


def _surface(value: str) -> DashboardSurface:
    surface = (value or "").strip().lower()
    if surface not in DEFAULT_DASHBOARD_CARDS:
        raise AppError("invalid_request", status_code=422)
    return surface


def _preferences(
    db: Session,
    *,
    tenant_id: str,
    surface: DashboardSurface,
) -> dict[str, DashboardCardPreference]:
    rows = db.scalars(
        ledger_scoped_select(DashboardCardPreference, tenant_id).where(
            DashboardCardPreference.surface == surface
        )
    )
    return {row.card_key: row for row in rows}


def _response(
    *,
    surface: DashboardSurface,
    prefs: dict[str, DashboardCardPreference],
) -> DashboardCardsResponse:
    cards = []
    has_saved_preferences = bool(prefs)
    default_count = len(DEFAULT_DASHBOARD_CARDS[surface])
    for default_position, definition in enumerate(DEFAULT_DASHBOARD_CARDS[surface]):
        pref = prefs.get(definition.key)
        fallback_position = (
            default_count + default_position
            if has_saved_preferences
            else default_position
        )
        cards.append(
            {
                "key": definition.key,
                "title": definition.title,
                "visible": pref.visible if pref is not None else True,
                "position": pref.position if pref is not None else fallback_position,
                "_default_position": default_position,
            }
        )
    cards.sort(key=lambda item: (int(item["position"]), int(item["_default_position"])))
    return DashboardCardsResponse(
        surface=surface,
        items=[
            {
                "key": str(item["key"]),
                "title": str(item["title"]),
                "visible": bool(item["visible"]),
                "position": int(item["position"]),
            }
            for item in cards
        ],
    )


def list_dashboard_cards(
    db: Session,
    *,
    tenant_id: str,
    surface: str,
) -> DashboardCardsResponse:
    resolved_surface = _surface(surface)
    return _response(
        surface=resolved_surface,
        prefs=_preferences(db, tenant_id=tenant_id, surface=resolved_surface),
    )


def update_dashboard_cards(
    db: Session,
    *,
    tenant_id: str,
    surface: str,
    payload: DashboardCardsUpdateRequest,
) -> DashboardCardsResponse:
    resolved_surface = _surface(surface)
    allowed = {definition.key for definition in DEFAULT_DASHBOARD_CARDS[resolved_surface]}
    seen: set[str] = set()
    positions: set[int] = set()
    for item in payload.cards:
        key = item.key.strip()
        if key not in allowed or key in seen:
            raise AppError("invalid_request", status_code=422)
        if item.position in positions:
            raise AppError("invalid_request", status_code=422)
        seen.add(key)
        positions.add(item.position)

    prefs = _preferences(db, tenant_id=tenant_id, surface=resolved_surface)
    now = now_utc()
    for key, pref in list(prefs.items()):
        if key not in seen:
            db.delete(pref)
            del prefs[key]
    db.flush()

    for pref in prefs.values():
        pref.position = pref.position + 10_000
    db.flush()

    for item in payload.cards:
        key = item.key.strip()
        pref = prefs.get(key)
        if pref is None:
            pref = DashboardCardPreference(
                tenant_id=tenant_id,
                surface=resolved_surface,
                card_key=key,
                position=item.position,
                visible=item.visible,
                created_at=now,
                updated_at=now,
            )
            db.add(pref)
            prefs[key] = pref
        else:
            pref.position = item.position
            pref.visible = item.visible
            pref.updated_at = now
    db.commit()
    return _response(
        surface=resolved_surface,
        prefs=_preferences(db, tenant_id=tenant_id, surface=resolved_surface),
    )
