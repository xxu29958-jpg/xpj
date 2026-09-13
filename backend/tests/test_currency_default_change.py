"""An explicit default change owns metadata, never historical money or receipts."""

from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import InstallationCurrencyAuditLog, InstallationCurrencyBinding, InstallationIdempotencyKey
from app.services import currency_adoption_service as adoption
from app.services import currency_default_service as defaults


class CommandStore:
    def __init__(self):
        self.binding = InstallationCurrencyBinding(singleton_id=1, state="ACTIVE", home_currency_code="CNY",
            minor_unit_exponent=2, rounding_mode="ROUND_HALF_UP", currency_contract_version=1,
            binding_revision=1, provenance="OWNER_ADOPTION", evidence_sha256="a" * 64,
            created_at=datetime(2026, 8, 1, tzinfo=UTC), activated_at=datetime(2026, 8, 2, tzinfo=UTC),
            updated_at=datetime(2026, 8, 2, tzinfo=UTC))
        self.keys = {}
        self.events = []
        self.pending = []
        self.db = Mock(spec=Session)
        self.db.get.side_effect = lambda model, key, **kwargs: self.keys.get(key)
        self.db.begin_nested.side_effect = nullcontext
        self.db.add.side_effect = self.pending.append
        self.db.flush.side_effect = self.flush
        self.db.commit.side_effect = self.commit
        self.db.rollback.side_effect = self.pending.clear
        self.db.execute.side_effect = AssertionError("default change must not write financial tables")

    def flush(self):
        for row in self.pending:
            if isinstance(row, InstallationCurrencyAuditLog) and row.event_id is None:
                row.event_id = str(uuid4())

    def commit(self):
        for row in self.pending:
            if isinstance(row, InstallationIdempotencyKey):
                self.keys[row.idempotency_key] = row
            else:
                assert isinstance(row, InstallationCurrencyAuditLog)
                self.events.append(row)
        self.pending.clear()


@pytest.fixture()
def store(monkeypatch):
    store = CommandStore()
    monkeypatch.setattr(defaults, "_load_binding", lambda db, **kwargs: store.binding)
    monkeypatch.setattr(defaults, "revalidate_currency_adoption_owner", lambda db, auth: auth)
    monkeypatch.setattr(adoption, "currency_adoption_evidence", Mock(side_effect=AssertionError("not adoption")))
    return store


def change(store, **kwargs):
    arguments = {"auth": SimpleNamespace(account_public_id="owner", device_public_id="desktop"),
        "idempotency_key": uuid4(), "expected_contract_version": 1, "home_code": "JPY", "expected_revision": 1,
        "reason": "Use yen for new entries and reports"}
    arguments.update(kwargs)
    return defaults.change_currency_binding_for_installation_owner(store.db, **arguments)


def test_change_preserves_adoption_identity_and_evidence_and_only_updates_default_metadata(store):
    before = dict(store.binding.__dict__)
    receipt = change(store, home_code=" jpy ")
    assert (receipt.home_currency_code, receipt.minor_unit_exponent, receipt.binding_revision) == ("JPY", 0, 2)
    assert receipt.operation == "currency_default_change"
    assert receipt.source_home_currency_code == "CNY"
    assert receipt.state == "ACTIVE"
    for field in ("singleton_id", "state", "currency_contract_version", "created_at", "activated_at", "evidence_sha256"):
        assert getattr(store.binding, field) == before[field]
    assert store.binding.provenance == "OWNER_DEFAULT_CHANGE"
    assert store.binding.updated_at.isoformat() == receipt.changed_at
    event = store.events[0]
    assert event.action == "OWNER_DEFAULT_CHANGE"
    assert event.before_snapshot["home_currency_code"] == "CNY"
    assert event.after_snapshot["home_currency_code"] == "JPY"
    assert (event.actor_account_public_id, event.actor_device_public_id) == ("owner", "desktop")
    assert len(store.keys) == len(store.events) == 1


def test_lost_ack_replay_returns_the_original_receipt_after_another_default_change(store):
    key = uuid4()
    first = change(store, idempotency_key=key)
    original_json = dict(store.keys[str(key)].receipt)
    change(store, home_code="EUR", expected_revision=2)
    replay = change(store, idempotency_key=key)
    assert replay == first
    assert asdict(replay) == original_json
    assert (store.binding.home_currency_code, store.binding.binding_revision) == ("EUR", 3)
    assert len(store.events) == len(store.keys) == 2


@pytest.mark.parametrize("changed", [{"home_code": "EUR"}, {"reason": "different"}, {"expected_revision": 2}])
def test_original_key_cannot_authorize_a_different_request(store, changed):
    key = uuid4()
    change(store, idempotency_key=key)
    with pytest.raises(AppError) as error:
        change(store, idempotency_key=key, **changed)
    assert error.value.error == "idempotency_key_reused"
    assert len(store.events) == len(store.keys) == 1


@pytest.mark.parametrize("changed, error_code", [
    ({"expected_revision": 0}, "currency_binding_state_conflict"),
    ({"expected_contract_version": 2}, "client_upgrade_required"),
    ({"home_code": "CNY"}, "invalid_request"),
    ({"home_code": "XYZ"}, "currency_not_supported"),
    ({"reason": " "}, "invalid_request"),
    ({"reason": "x" * 501}, "invalid_request"),
])
def test_refused_change_does_not_create_an_event_or_new_revision(store, changed, error_code):
    with pytest.raises(AppError) as error:
        change(store, **changed)
    assert error.value.error == error_code
    assert (store.binding.home_currency_code, store.binding.binding_revision) == ("CNY", 1)
    assert not store.events and not store.keys


def test_change_cannot_activate_an_unselected_installation(store):
    store.binding.state = "EMPTY"
    with pytest.raises(AppError) as error:
        change(store)
    assert error.value.error == "currency_binding_state_conflict"


def test_accepted_receipt_still_requires_current_installation_owner_authority(store, monkeypatch):
    key = uuid4()
    change(store, idempotency_key=key)
    monkeypatch.setattr(defaults, "revalidate_currency_adoption_owner",
        Mock(side_effect=AppError("permission_denied", status_code=403)))
    with pytest.raises(AppError) as error:
        change(store, idempotency_key=key)
    assert error.value.status_code == 403
    assert len(store.events) == 1


def test_preview_reads_current_default_without_restricting_choice_to_historical_currencies(store):
    preview = defaults.currency_change_preview(store.db, auth=SimpleNamespace())
    assert preview.home_currency_code == "CNY"
    assert preview.binding_revision == 1
    assert set(preview.allowed_home_currency_codes) == {"CNY", "USD", "EUR", "GBP", "JPY", "HKD", "KRW"}
    assert not store.pending


def test_default_change_does_not_overwrite_an_adoption_key_or_receipt(store):
    key = uuid4()
    original = {"operation": "currency_binding_adoption", "event_id": str(uuid4()), "state": "ACTIVE",
        "home_currency_code": "CNY", "minor_unit_exponent": 2, "rounding_mode": "ROUND_HALF_UP",
        "currency_contract_version": 1, "binding_revision": 1, "evidence_sha256": "a" * 64,
        "activated_at": store.binding.activated_at.isoformat()}
    store.keys[str(key)] = InstallationIdempotencyKey(idempotency_key=str(key),
        operation="currency_binding_adoption", request_fingerprint="old-fingerprint", status="succeeded", receipt=original)
    with pytest.raises(AppError) as error:
        change(store, idempotency_key=key)
    assert error.value.error == "idempotency_key_reused"
    change(store)
    replay = adoption._claim_idempotency_key(store.db, key=str(key), fingerprint="old-fingerprint")
    assert asdict(replay) == original


def test_missing_original_receipt_never_falls_back_to_the_current_default(store):
    key = uuid4()
    change(store, idempotency_key=key)
    store.keys[str(key)].receipt = None
    with pytest.raises(AppError) as error:
        change(store, idempotency_key=key)
    assert error.value.error == "currency_binding_corrupt"
