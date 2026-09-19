"""Publication evidence is not erased by an unknown historical confirmation time."""

from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.models import Expense
from app.services import expense_revision_service as revisions


@pytest.mark.parametrize(("status", "fact_revision", "published"), [
    ("confirmed", 0, True), ("rejected", 2, True), ("pending", 0, False),
])
def test_unknown_time_preserves_published_fact_boundary(monkeypatch, status, fact_revision, published):
    db = Mock(spec=Session)
    db.scalar.return_value = None
    db.execute.return_value.all.return_value = []
    expense = Expense(id=1, tenant_id="owner", status=status, confirmed_at=None,
        expense_time=None, fact_revision=fact_revision, row_version=3)
    snapshot = {"id": 1, "amount_cents": 1234, "confirmed_at": None, "expense_time": None}
    monkeypatch.setattr(revisions, "expense_fact_snapshot", lambda *a: dict(snapshot))
    prepared = revisions.prepare_correction_revision(db, expense)
    assert (prepared is not None) == published
    assert expense.confirmed_at is None and expense.expense_time is None
    if published:
        assert prepared.before == snapshot and prepared.previous_row_version == 3
    if status == "confirmed":
        baseline = db.add.call_args.args[0]
        assert baseline.revision_number == 1 and baseline.after_snapshot == snapshot
        assert expense.fact_revision == 1
    else:
        db.add.assert_not_called()
