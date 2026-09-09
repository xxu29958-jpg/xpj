"""Rule application records the rule that the user previewed, despite ORM expiry."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.models import CategoryRule, Expense, RuleApplicationBatch, RuleApplicationChange
from app.services.rule_application_service import _apply, _common, _preview


def test_rule_rename_during_correction_cannot_rewrite_preview_audit(monkeypatch):
    now = datetime(2026, 9, 9, tzinfo=UTC)
    rule = CategoryRule(id=3, keyword="store", category="购物", enabled=True, priority=1, updated_at=now)
    expenses = [Expense(id=value, tenant_id="owner", merchant="store", category="其他", row_version=1,
        home_currency_code="CNY", amount_cents=1200, expense_time=now, updated_at=now) for value in (1, 2)]
    for module in (_preview, _apply):
        monkeypatch.setattr(module, "_rule_application_candidates", lambda *a, **k: (expenses, False))
        monkeypatch.setattr(module, "_enabled_rules", lambda *a, **k: [rule])
        monkeypatch.setattr(module, "enabled_merchant_alias_map", lambda *a, **k: {})
        monkeypatch.setattr(module, "_ocr_text_by_expense_id", lambda *a, **k: {})
    monkeypatch.setattr(_preview, "_non_auto_fillable_category_count", lambda *a, **k: 0)
    monkeypatch.setattr(_apply, "authorize_currency_metadata_write", lambda *a, **k: None)
    monkeypatch.setattr(_common, "prepare_correction_revision", lambda *a, **k: object())
    monkeypatch.setattr(_common, "ocr_draft_fields_after_clearing", lambda *a, **k: None)
    selected = {}
    def claim(_db, _model, **kwargs):
        selected["expense"] = expenses[kwargs["pk_id"] - 1]
        return 1
    monkeypatch.setattr(_common, "claim_row_with_token", claim)
    reasons = []
    monkeypatch.setattr(_common, "record_prepared_correction_revision", lambda *a, **k: reasons.append(k["reason"]))
    persisted = []
    def add(row):
        if isinstance(row, RuleApplicationBatch):
            row.id = 9
        persisted.append(row)
    db = SimpleNamespace(add=add, flush=lambda: None, commit=lambda: None,
        scalar=lambda query: selected["expense"],
        expire_all=lambda: setattr(rule, "keyword", "renamed-after-preview"))
    preview = _preview.preview_apply_rules_to_confirmed(db, tenant_id="owner")
    result = _apply.apply_rules_to_confirmed(db, tenant_id="owner", preview_token=preview["preview_token"])
    assert result == (2, 2, False)
    changes = [row for row in persisted if isinstance(row, RuleApplicationChange)]
    assert [(row.rule_id, row.matched_keyword, row.after_category) for row in changes] == [
        (3, "store", "购物"), (3, "store", "购物")]
    assert reasons == ["规则“store”更正分类", "规则“store”更正分类"]
