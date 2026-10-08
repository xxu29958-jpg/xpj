"""Catalog form intent and explicit read-only review for the existing Web surface."""
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import MerchantCatalogDeleteRequest, MerchantCatalogMergeRequest, MerchantCatalogUpdateRequest
from app.services.merchant_catalog_service import get_merchant_catalog

CATALOG_ACTIONS = {"rename": "重命名", "merge": "合并商家", "toggle": "显示或隐藏", "delete": "移入回收站"}


class MerchantCommandForm(BaseModel):
    ledger_id: str = ""
    merchant: str = ""
    search: str = ""
    status: str = "all"
    source_name: str = ""
    target_name: str = ""
    display_name: str = ""
    expected_row_version: str = ""
    target: str = ""
    alias_policy: str = ""
    next_status: str = ""
    draft_scope: str = ""
    idempotency_key: str = ""
    draft_ref: str = ""
    review_latest: bool = False


def catalog_payload(kind: str, values: MerchantCommandForm):
    try:
        version = int(values.expected_row_version)
        if kind == "merge":
            target_id, _, target_version = values.target.rpartition(":")
            return MerchantCatalogMergeRequest(expected_row_version=version, target_public_id=target_id,
                target_row_version=int(target_version), alias_policy=values.alias_policy)
        if kind == "delete":
            return MerchantCatalogDeleteRequest(expected_row_version=version)
        if kind == "rename":
            return MerchantCatalogUpdateRequest(expected_row_version=version, display_name=values.display_name)
        return MerchantCatalogUpdateRequest(expected_row_version=version, status=values.next_status)
    except (ValidationError, ValueError) as exc:
        raise AppError("invalid_request", "请核对商家名称、原版本及本次操作的选择。", status_code=422) from exc


def review_catalog_form(db: Session, kind: str, values: MerchantCommandForm) -> MerchantCommandForm:
    source = get_merchant_catalog(db, tenant_id=values.ledger_id, public_id=values.merchant)
    if source.status not in {"active", "hidden"}:
        raise AppError("state_conflict", "原商家已经合并，原输入仍保留，请核对目录。", status_code=409)
    updates = {"source_name": source.display_name, "expected_row_version": str(source.row_version)}
    if kind == "merge" and values.target:
        target_id = values.target.rpartition(":")[0]
        try:
            target = get_merchant_catalog(db, tenant_id=values.ledger_id, public_id=target_id)
        except AppError as exc:
            if exc.error != "not_found":
                raise
        else:
            updates.update(target=f"{target.public_id}:{target.row_version}", target_name=target.display_name)
    return values.model_copy(update=updates)


def catalog_form_context(request, ctx: dict, scope: dict | None, *, kind: str,
                         values: MerchantCommandForm | None, result: str, error: str) -> dict:
    import json
    from urllib.parse import urlencode
    from uuid import uuid4

    kind = kind or request.query_params.get("command", "")
    if kind not in CATALOG_ACTIONS:
        return {"command_kind": ""}
    item = ctx["selected_merchant"]
    if values is None:
        values = MerchantCommandForm(ledger_id=ctx["selected_ledger_id"], merchant=request.query_params.get("merchant", ""),
            search=ctx["merchant_search"], status=ctx["merchant_status"], source_name=item.display_name if item else "",
            display_name=item.display_name if item else "", expected_row_version=str(item.row_version) if item else "",
            next_status="hidden" if item and item.status == "active" else "active",
            draft_scope=json.dumps(scope) if scope else "", idempotency_key=str(uuid4()), draft_ref=str(uuid4()))
    source = next((row for row in ctx["catalog"] if row.public_id == values.merchant), None)
    target_id = values.target.rpartition(":")[0]
    target_available = any(row.public_id == target_id and row.public_id != values.merchant and row.status == "active"
                           for row in ctx["catalog"])
    return {"merchant_view": "command", "command_kind": kind, "command_label": CATALOG_ACTIONS[kind],
            "command_form": values, "command_result": result, "command_error": error,
            "command_target_available": target_available,
            "command_available": source is not None and source.status in {"active", "hidden"},
            "selected_merchant": source,
            "directory_href": "/web/merchants?" + urlencode({"ledger_id": values.ledger_id,
                "search": values.search, "status": values.status})}
