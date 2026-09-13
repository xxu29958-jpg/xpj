"""A local first-write token means the accepted creation basis, not current state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import expense_query


@pytest.fixture
def lookup(monkeypatch):
    expense = SimpleNamespace(id=42, row_version=9, source="手动记账")
    read = Mock(return_value=SimpleNamespace(id=42, row_version=3))
    monkeypatch.setattr(expense_query, "resolve_expense", lambda *_args, **_kwargs: expense)
    monkeypatch.setattr(expense_query, "read_manual_creation_receipt", read, raising=False)
    return expense, read


def test_original_local_zero_uses_accepted_version_and_exact_device_scope(lookup):
    _, read = lookup
    result = expense_query.resolve_expense_for_mutation(None, "owner", "local:original",
        device_id=7, expected_row_version=0)
    assert result == (42, 3)
    read.assert_called_once_with(None, tenant_id="owner", device_id=7, client_ref="original")


@pytest.mark.parametrize(("ref", "version"), [("local:original", 4), ("42", 0), (42, 6)])
def test_known_token_and_server_ids_keep_their_original_occ(lookup, ref, version):
    _, read = lookup
    assert expense_query.resolve_expense_for_mutation(None, "owner", ref,
        device_id=7, expected_row_version=version) == (42, version)
    read.assert_not_called()


@pytest.mark.parametrize("receipt", [None, SimpleNamespace(id=90, row_version=3)])
def test_unproven_original_basis_cannot_use_current_version(lookup, receipt):
    _, read = lookup
    read.return_value = receipt
    assert expense_query.resolve_expense_for_mutation(None, "owner", "local:original",
        device_id=7, expected_row_version=0) == (42, 0)


def test_upload_row_cannot_borrow_a_manual_first_write_receipt(lookup):
    expense, _ = lookup
    expense.source = "iPhone截图"
    assert expense_query.resolve_expense_for_mutation(None, "owner", "local:original",
        device_id=7, expected_row_version=0) == (42, 0)
