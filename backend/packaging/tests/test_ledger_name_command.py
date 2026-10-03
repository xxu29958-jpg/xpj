"""A short business counterexample; PostgreSQL covers authorization and transactions."""

from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.models import Ledger
from app.services import ledger_service


def test_name_change_keeps_identity_and_calendar_and_rejects_a_stale_different_name(monkeypatch):
    ledger = Ledger(ledger_id="family", name="家庭", owner_account_id=7, calendar_revision=3)
    audits = []
    db = SimpleNamespace(scalar=lambda *_args: ledger, add=audits.append, commit=lambda: None)
    monkeypatch.setattr(ledger_service, "lock_and_revalidate_mutation_actor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ledger_service, "get_ledger_for_account", lambda *_args, **_kwargs: (ledger, "owner"))

    for _ in range(2):
        saved = ledger_service.rename_ledger(db, account_id=7, ledger_id="family", name="  我们的家  ",
                                            expected_name="家庭", auth=None)
        assert saved.name == "我们的家"
    assert (ledger.ledger_id, ledger.owner_account_id, ledger.calendar_revision) == ("family", 7, 3)
    assert len(audits) == 1 and audits[0].action == "ledger_renamed"

    with pytest.raises(AppError) as failure:
        ledger_service.rename_ledger(db, account_id=7, ledger_id="family", name="旧页面输入",
                                     expected_name="家庭", auth=None)
    assert failure.value.status_code == 409
    assert ledger.name == "我们的家" and len(audits) == 1
