"""Review raw intent against peer changes without running a financial command."""
from app.routes._web_correction_review import _current_review_choices, _review_rows, _review_scalars
from app.routes._web_correction_snapshot import ITEM_FIELDS, SPLIT_FIELDS


def test_review_requires_explicit_choices_for_peer_money_and_note_but_adopts_untouched_fields():
    basis = {"values": {"amount_yuan": "10.00", "original_currency": "CNY", "merchant": "原商家", "note": "原备注"}}
    current = {"amount_yuan": "1500", "original_currency": "JPY", "merchant": "后来商家", "note": "后来备注"}
    raw = {"amount_yuan": " 0005.50 ", "original_currency": "CNY", "merchant": "原商家", "note": "自己的备注"}
    prepared, required = _review_scalars(raw, basis, current, "")
    assert required == {"amount_yuan", "note"}
    prepared, required = _review_scalars(raw, basis, current, "", {"amount_yuan": "keep", "note": "current"})
    assert not required
    assert prepared == {"amount_yuan": " 0005.50 ", "original_currency": "CNY", "merchant": "后来商家", "note": "后来备注"}
    prepared, required = _review_scalars(raw, basis, current, "", {"amount_yuan": "keep", "note": "keep"})
    assert prepared == {"amount_yuan": " 0005.50 ", "original_currency": "CNY", "merchant": "后来商家", "note": "自己的备注"}
    assert current["original_currency"] == "JPY" and raw["merchant"] == "原商家"


def test_review_does_not_request_a_choice_for_the_same_edit_or_an_unchanged_peer():
    basis = {"values": {"category": "其他", "note": "原备注", "merchant": "商家"}}
    current = {"category": "餐饮", "note": "原备注", "merchant": "新商家"}
    raw = {"category": "餐饮", "note": "我的原因", "merchant": "商家"}
    values, required = _review_scalars(raw, basis, current, "")
    assert not required
    assert values == {"category": "餐饮", "note": "我的原因", "merchant": "新商家"}


def test_choices_are_bound_to_the_current_version_shown_including_collections():
    submitted = {"review_current_version": "2", "review_category_choice": "keep", "review_items_choice": "current"}
    assert _current_review_choices(submitted, "2") == {"category": "keep", "items": "current"}
    assert _current_review_choices(submitted, "3") == {}
    assert _current_review_choices({"review_category_choice": "keep"}, "2") == {}


def test_peer_replaced_items_require_choice_and_keep_never_borrows_the_new_source_identity():
    old = [{"public_id": "old", "name": "识别名称", "amount_yuan": "5.00", "kind": "product"}]
    raw = [{**old[0], "name": "人工原稿"}]
    current = [{"public_id": "peer-new", "name": "后来明细", "amount_yuan": "7.00", "kind": "product"}]
    retained, required = _review_rows(raw, old, current, ITEM_FIELDS, "")
    assert required and retained == raw
    kept, required = _review_rows(raw, old, current, ITEM_FIELDS, "keep")
    assert not required
    assert kept[0]["name"] == "人工原稿" and kept[0]["public_id"] == ""
    assert kept[1]["public_id"] == "peer-new" and kept[1]["name"] == ""
    adopted, required = _review_rows(raw, old, current, ITEM_FIELDS, "current")
    assert not required and adopted == current


def test_keep_does_not_rewrite_a_current_disabled_member_split():
    old = [{"public_id": "split", "member_id": 2, "amount_yuan": "5.00", "note": "旧备注"}]
    raw = [{**old[0], "amount_yuan": "3.00"}]
    current = [{**old[0], "disabled": True, "note": "后来约定"}]
    prepared, required = _review_rows(raw, old, current, SPLIT_FIELDS, "keep")
    assert not required and prepared == current
