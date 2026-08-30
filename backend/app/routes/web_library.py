"""Reference Library hub for the current Web ledger.

The hub composes existing read owners for wayfinding only.  Category, merchant,
tag, rule, and recycle-bin commands remain owned by their existing services and
canonical section routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    templates,
)
from app.services.category_preference_service import list_category_preferences
from app.services.merchant_alias_service import list_merchant_aliases
from app.services.merchant_catalog_service import list_merchant_catalog
from app.services.recycle_bin_service import list_recycle_bin_items
from app.services.rule_service import list_rules
from app.services.tag_management_service import list_tags_with_usage

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/library", response_class=HTMLResponse)
def web_reference_library(
    request: Request,
    ledger_id: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    categories = list_category_preferences(db, tenant_id=selected_id)
    merchants = list_merchant_catalog(
        db,
        tenant_id=selected_id,
        include_hidden=True,
    )
    aliases = list_merchant_aliases(db, selected_id)
    tags = list_tags_with_usage(db, selected_id)
    rules = list_rules(db, selected_id)
    recycle_bin = list_recycle_bin_items(db, tenant_id=selected_id)

    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="资料库",
    )
    ctx.update(
        library_counts={
            "custom_categories": len(categories),
            "merchants": len(merchants),
            "merchant_aliases": len(aliases),
            "tags": len(tags),
            "rules_enabled": sum(1 for rule in rules if rule.enabled),
            "rules_total": len(rules),
            "recycle_total": len(recycle_bin.items),
            "recycle_short_window": recycle_bin.short_window_count,
        },
        q="?ledger_id=" + selected_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context=ctx,
    )
