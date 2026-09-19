"""Relationship navigation never grants access to the other participant's bills."""

from types import SimpleNamespace

import pytest

from app.errors import AppError


def test_source_ledger_member_gets_no_unusable_cross_ledger_debt_link(monkeypatch):
    from app.routes import _web_relationship_links as links

    seen = []
    def authorize(db, *, public_id, ledger_id, account_id):
        seen.append((public_id, ledger_id, account_id))
        raise AppError("debt_not_found", status_code=404)
    monkeypatch.setattr(links, "get_participant_debt_response", authorize)
    assert links.authorized_debt_href(object(), public_id="other-debt", selected_id="source", account_id=3) == ""
    assert seen == [("other-debt", "source", 3)]


def test_participant_link_keeps_current_ledger_without_private_expense(monkeypatch):
    from app.routes import _web_relationship_links as links

    monkeypatch.setattr(links, "get_participant_debt_response", lambda *_a, **_kw: SimpleNamespace())
    assert links.authorized_debt_href(object(), public_id="shared-debt", selected_id="mine", account_id=2) == "/web/debts/shared-debt?ledger_id=mine"


def test_authorization_failure_is_not_hidden_as_missing_relationship(monkeypatch):
    from app.routes import _web_relationship_links as links

    def failed(*_a, **_kw):
        raise AppError("permission_denied", status_code=403)
    monkeypatch.setattr(links, "get_participant_debt_response", failed)
    with pytest.raises(AppError) as caught:
        links.authorized_debt_href(object(), public_id="shared-debt", selected_id="mine", account_id=2)
    assert caught.value.error == "permission_denied"
