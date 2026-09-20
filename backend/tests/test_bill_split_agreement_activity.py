"""New agreements remain discoverable in the existing, paginated fact history."""

from datetime import timedelta

from app.models import Debt
from app.services.debt_service._activity import list_debt_activity
from app.services.time_service import ensure_utc
from tests.test_bill_split_agreement_commands import WHEN, _accept, _paid, _request
from tests.test_bill_split_agreement_commands import agreement_db as agreement_db


def history(db, public_id="original", *, page=1, page_size=100):
    return list_debt_activity(db, tenant_id="sender-private", actor_account_id=2,
        public_id=public_id, page=page, page_size=page_size)


def test_original_and_return_timeline_retain_accepted_terms_without_private_ledger(agreement_db):
    db = agreement_db
    _paid(db, 1, 4_000)
    change = _accept(db, _request(db, share=2_000, net=-2_000))
    returned = db.get(Debt, change.return_debt_id)
    for public_id in ("original", returned.public_id):
        result = history(db, public_id)
        terms = next(item for item in result.items if item.kind == "split_agreement_changed")
        assert terms.public_id == change.public_id
        assert terms.actor_is_you
        assert terms.split_change.status == "accepted"
        assert terms.split_change.new_share_amount_cents == 2_000
        assert terms.split_change.settlement_net_amount_cents == -2_000
        assert terms.split_change.original_paid_amount_cents == 4_000
        assert "receiver-private" not in result.model_dump_json()
    assert any(item.kind == "repayment" for item in history(db).items)


def test_replacement_history_pages_every_intent_once_without_creating_fake_payments(agreement_db):
    db = agreement_db
    first = _request(db, share=2_000, net=2_000)
    second = _request(db, share=3_000, net=3_000, actor=2, supersedes=first.public_id)
    all_items = history(db).items
    resolved = next(item for item in all_items if item.kind == "split_change_resolved")
    assert resolved.split_change.status == "superseded"
    assert resolved.split_change.public_id == first.public_id
    assert any(item.split_change and item.split_change.public_id == second.public_id for item in all_items)
    assert not any(item.kind in {"repayment", "split_agreement_changed"} for item in all_items)
    paged = [item for page in range(1, (len(all_items) + 1) // 2 + 1) for item in history(db, page=page, page_size=2).items]
    assert [(item.kind, item.public_id) for item in paged] == [(item.kind, item.public_id) for item in all_items]


def test_expiry_discovered_by_a_new_proposal_keeps_expiry_time_and_no_participant(agreement_db, monkeypatch):
    from app.services.bill_split_service import _agreement_commands

    db = agreement_db
    monkeypatch.setattr(_agreement_commands, "now_utc", lambda: WHEN)
    first = _request(db, share=2_000, net=2_000)
    expires_at = ensure_utc(first.expires_at)
    discovered_at = expires_at + timedelta(days=2)
    monkeypatch.setattr(_agreement_commands, "now_utc", lambda: discovered_at)
    second = _request(db, share=3_000, net=3_000, actor=2)
    assert first.status == "expired" and second.status == "pending"
    assert ensure_utc(first.resolved_at) == expires_at
    assert first.resolved_by_account_id is None
    resolved = next(item for item in history(db).items if item.kind == "split_change_resolved")
    assert ensure_utc(resolved.recorded_at) == expires_at
    assert not resolved.actor_is_you
    assert resolved.actor_display_name is None


def test_actual_timeline_template_explains_terms_separately_from_payment(agreement_db):
    from app.routes._web_debt_activity import activity_view
    from app.routes.web_common import templates

    db = agreement_db
    _paid(db, 1, 4_000)
    _accept(db, _request(db, share=2_000, net=-2_000))
    html = templates.get_template("_debt_activity.html").render(
        activity=activity_view(history(db), selected_id="sender-private"),
        debt={"is_member": True, "public_id": "original"}, can_write=False,
        action_form={"kind": ""}, selected_ledger_id="sender-private",
    )
    assert "双方接受新约定" in html
    assert "份额 ¥40.00 → ¥20.00" in html
    assert "发起方待返还 ¥20.00" in html
    assert "原付款 ¥40.00" in html
    assert "还款到账" in html
