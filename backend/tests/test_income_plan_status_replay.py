"""Exercise the actual status owner without opening a database connection."""

from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IncomePlanRevision, MonthlyIncomePlan
from app.services import income_plan_service
from app.services.income_plan_service import _history


@pytest.fixture
def isolated_owner(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(Engine, "connect", Mock(side_effect=AssertionError("database connections are forbidden")))
        patch.setattr(_history, "accounting_zone", lambda: UTC)
        yield patch


def _prepare_replay(patch, *, action: str, after_occ: bool, revision: IncomePlanRevision | None):
    target = "archived" if action == "archive" else "active"
    current = MonthlyIncomePlan(id=7, tenant_id="owner", public_id="plan", row_version=4, status=target)
    stale = MonthlyIncomePlan(id=7, tenant_id="owner", public_id="plan", row_version=3,
        status="active" if action == "archive" else "archived")
    db = Mock(spec=Session)
    db.scalar.side_effect = [date(2026, 8, 1), revision] if after_occ else [revision]
    patch.setattr(income_plan_service, "_require_plan", Mock(side_effect=[stale, current] if after_occ else [current]))
    patch.setattr(income_plan_service, "resolve_write_capability", Mock())
    patch.setattr(income_plan_service, "claim_row_with_token", Mock(return_value=0))
    return db, current


@pytest.mark.parametrize("action", ["archive", "restore"])
@pytest.mark.parametrize("after_occ", [False, True], ids=["first-read", "after-occ"])
def test_a_later_month_same_status_does_not_complete_the_original_command(isolated_owner, action, after_occ) -> None:
    revision = IncomePlanRevision(revision_number=4, intent_month=date(2026, 10, 1),
        status="archived" if action == "archive" else "active")
    db, _ = _prepare_replay(isolated_owner, action=action, after_occ=after_occ, revision=revision)

    with pytest.raises(AppError) as error:
        getattr(income_plan_service, f"{action}_income_plan")(
            db, tenant_id="owner", public_id="plan", expected_row_version=3,
            intent_month="2026-09", now=datetime(2026, 12, 2, tzinfo=UTC),
        )

    assert error.value.error == "state_conflict"
    assert error.value.status_code == 409
    db.commit.assert_not_called()
    db.add.assert_not_called()


@pytest.mark.parametrize("action", ["archive", "restore"])
@pytest.mark.parametrize("after_occ", [False, True], ids=["first-read", "after-occ"])
def test_same_month_status_replay_keeps_the_existing_head(isolated_owner, action, after_occ) -> None:
    revision = IncomePlanRevision(revision_number=4, intent_month=date(2026, 9, 1),
        status="archived" if action == "archive" else "active")
    db, current = _prepare_replay(isolated_owner, action=action, after_occ=after_occ, revision=revision)

    replay = getattr(income_plan_service, f"{action}_income_plan")(
        db, tenant_id="owner", public_id="plan", expected_row_version=3,
        intent_month="2026-09", now=datetime(2026, 12, 2, tzinfo=UTC),
    )

    assert replay is current
    assert replay.row_version == 4
    db.commit.assert_not_called()
    db.add.assert_not_called()
    db.flush.assert_not_called()


@pytest.mark.parametrize("revision", [
    None,
    IncomePlanRevision(revision_number=4, intent_month=None, status="archived"),
    IncomePlanRevision(revision_number=3, intent_month=date(2026, 9, 1), status="archived"),
    IncomePlanRevision(revision_number=4, intent_month=date(2026, 9, 1), status="active"),
], ids=["missing", "undated-baseline", "different-head", "different-status"])
@pytest.mark.parametrize("after_occ", [False, True], ids=["first-read", "after-occ"])
def test_status_replay_requires_a_revision_that_represents_the_head(isolated_owner, revision, after_occ) -> None:
    db, _ = _prepare_replay(isolated_owner, action="archive", after_occ=after_occ, revision=revision)

    with pytest.raises(AppError) as error:
        income_plan_service.archive_income_plan(
            db, tenant_id="owner", public_id="plan", expected_row_version=3,
            intent_month="2026-09", now=datetime(2026, 12, 2, tzinfo=UTC),
        )

    assert error.value.error == "state_conflict"
    db.commit.assert_not_called()
    db.add.assert_not_called()
