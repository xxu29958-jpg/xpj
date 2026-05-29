from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_atomic_promise_commit_counter_ignores_nested_functions() -> None:
    mod = importlib.reload(importlib.import_module("_audit_atomic_promise_vs_commits"))
    tree = ast.parse(
        '''
def outer(db):
    """atomic write."""
    db.commit()
    def nested():
        db.commit()
    return nested
'''
    )
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    assert mod._commit_count(function) == 1


def test_allowlist_reason_placeholder_check_uses_word_boundaries() -> None:
    mod = importlib.reload(importlib.import_module("_audit_allowlist_reasons"))

    assert mod._reason_uses_placeholder("tracker is unknown")
    assert not mod._reason_uses_placeholder("tracker is wiped on unknown-host responses")
    assert not mod._reason_uses_placeholder("known upstream route keeps laterally safe ownership")


def test_allowlist_reason_scope_claims_are_machine_checked() -> None:
    mod = importlib.reload(importlib.import_module("_audit_allowlist_reasons"))

    assert mod._scope_claim_failure(
        "POST /api/ledgers/{ledger_id}/members/{member_id}/role",
        "owner-console-only - role assignment",
    )
    assert mod._scope_claim_failure(
        "POST /web/budgets/save",
        "single-writer monthly budget",
    )
    assert mod._scope_claim_failure(
        "POST /api/admin/devices/{public_id}/rename",
        "owner-only - device rename under admin API",
    ) is None
    assert mod._scope_claim_failure(
        "POST /owner/upload-links/{public_id}/limits",
        "owner-console-only - single-writer rate-limit edit",
    ) is None
