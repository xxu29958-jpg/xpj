from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_parser_reads_every_dispatcher_implementation_in_one_file() -> None:
    mod = importlib.reload(importlib.import_module("_audit_android_outbox_dispatcher_coverage"))
    source = """
class CreateExpenseOffsetDispatcher(
    private val api: ApiService,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateExpenseOffset
}

class VoidExpenseOffsetDispatcher(
    private val api: ApiService,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.VoidExpenseOffset
}
"""

    assert mod.parse_dispatchers({"ExpenseOffsetDispatchers.kt": source}) == {
        "CreateExpenseOffset": "CreateExpenseOffsetDispatcher",
        "VoidExpenseOffset": "VoidExpenseOffsetDispatcher",
    }
