"""Relationship navigation never grants access to the other participant's bills."""

from types import SimpleNamespace

import pytest

from app.errors import AppError


def test_source_ledger_member_gets_no_unusable_cross_ledger_debt_link(monkeypatch):
    from app.routes import _web_relationship_links as links

    seen = []
    def authorize(db, *, public_ids, ledger_id, account_id):
        seen.append((public_ids, ledger_id, account_id))
        return frozenset()
    monkeypatch.setattr(links, "participant_accessible_debt_public_ids", authorize)
    assert links.authorized_debt_hrefs(object(), public_ids={"other-debt"}, selected_id="source", account_id=3) == {}
    assert seen == [({"other-debt"}, "source", 3)]


def test_participant_link_keeps_current_ledger_without_private_expense(monkeypatch):
    from app.routes import _web_relationship_links as links

    monkeypatch.setattr(links, "participant_accessible_debt_public_ids", lambda *_a, **_kw: {"shared-debt"})
    assert links.authorized_debt_hrefs(object(), public_ids={"shared-debt"}, selected_id="mine", account_id=2) == {
        "shared-debt": "/web/debts/shared-debt?ledger_id=mine"}


def test_authorization_failure_is_not_hidden_as_missing_relationship(monkeypatch):
    from app.routes import _web_relationship_links as links

    def failed(*_a, **_kw):
        raise AppError("permission_denied", status_code=403)
    monkeypatch.setattr(links, "participant_accessible_debt_public_ids", failed)
    with pytest.raises(AppError) as caught:
        links.authorized_debt_hrefs(object(), public_ids={"shared-debt"}, selected_id="mine", account_id=2)
    assert caught.value.error == "permission_denied"


def test_accepted_split_links_authorize_all_candidates_in_one_batch(monkeypatch):
    from app.routes import _web_relationship_links as links

    invitations = [
        SimpleNamespace(
            public_id=f"invite-{index}",
            status="accepted",
            sender_ledger_id="source",
            sender_expense_id=index,
        )
        for index in range(50)
    ]
    monkeypatch.setattr(
        links,
        "list_accepted_source_relationships",
        lambda _db, *, sender_ledger_id, sender_expense_id: (
            SimpleNamespace(
                invitation_public_id=f"invite-{sender_expense_id}",
                debt_public_id=f"debt-{sender_expense_id}",
            ),
        ),
    )
    seen = []

    def authorize(_db, *, public_ids, ledger_id, account_id):
        seen.append((public_ids, ledger_id, account_id))
        return frozenset(public_ids)

    monkeypatch.setattr(links, "participant_accessible_debt_public_ids", authorize)

    result = links.accepted_split_debt_links(
        object(), invitations, selected_id="source", account_id=3,
    )

    assert len(result) == 50
    assert seen == [({f"debt-{index}" for index in range(50)}, "source", 3)]


def test_offset_fact_authorizes_relationship_links_once(monkeypatch):
    from app.routes import _web_expense_offset_fact as offset_fact
    from app.routes import _web_relationship_links as links

    accepted = [{"debt_public_id": f"debt-{index}"} for index in range(50)]
    accepted.append({"debt_public_id": None})
    monkeypatch.setattr(offset_fact, "expense_fact_bundle", lambda *_a, **_kw: object())
    monkeypatch.setattr(offset_fact, "offset_fact_view",
        lambda *_a, **_kw: {"offset_relationship_impacts": {"accepted": accepted}})
    monkeypatch.setattr(offset_fact, "resolve_web_actor_account_id", lambda *_a, **_kw: 3)
    seen = []

    def authorize(_db, *, public_ids, ledger_id, account_id):
        seen.append((public_ids, ledger_id, account_id))
        return frozenset(public_ids - {"debt-49"})

    monkeypatch.setattr(links, "participant_accessible_debt_public_ids", authorize)
    view = offset_fact.expense_offset_fact_view(object(), "source", 7, False, object())
    assert view["offset_relationship_impacts"]["accepted"] == accepted
    assert seen == [({f"debt-{index}" for index in range(50)}, "source", 3)]
    assert accepted[0]["debt_href"] == "/web/debts/debt-0?ledger_id=source"
    assert accepted[-2]["debt_href"] == accepted[-1]["debt_href"] == ""


def test_offset_fact_keeps_fact_when_optional_actor_cannot_be_resolved(monkeypatch):
    from app.routes import _web_expense_offset_fact as offset_fact

    accepted = [{"debt_public_id": "shared-debt"}]
    monkeypatch.setattr(offset_fact, "expense_fact_bundle", lambda *_a, **_kw: object())
    monkeypatch.setattr(
        offset_fact,
        "offset_fact_view",
        lambda *_a, **_kw: {"offset_relationship_impacts": {"accepted": accepted}},
    )

    def unresolved(*_a, **_kw):
        raise AppError("ledger_forbidden", status_code=403)

    monkeypatch.setattr(offset_fact, "resolve_web_actor_account_id", unresolved)
    monkeypatch.setattr(
        offset_fact,
        "authorized_debt_hrefs",
        lambda *_a, **_kw: pytest.fail("optional links must be skipped without an actor"),
    )

    view = offset_fact.expense_offset_fact_view(
        object(), "loopback-visible", 7, False, object(),
    )

    assert view["offset_relationship_impacts"]["accepted"] == accepted
    assert "debt_href" not in accepted[0]
