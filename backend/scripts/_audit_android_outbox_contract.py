"""Release gate for the Android outbox design contract.

The backend release audit is the repo-wide preflight entrypoint, so it also
checks the Android offline queue invariants that previously regressed:
injectable scheduler wiring, one aggregated status surface, and SQL-side
runnable selection that de-duplicates targets before applying LIMIT.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_ROOT = REPO_ROOT / "android" / "app" / "src"


def _read(relative_path: str) -> str:
    return (ANDROID_ROOT / relative_path).read_text(encoding="utf-8")


def _fail(message: str) -> None:
    print(f"FAIL: {message}")


def main() -> int:
    ok = True

    scheduler = _read("main/java/com/ticketbox/data/repository/OutboxScheduler.kt")
    if "class OutboxScheduler(" not in scheduler or "object OutboxScheduler" in scheduler:
        ok = False
        _fail("OutboxScheduler must stay an injectable class, not a singleton object")

    container = _read("main/java/com/ticketbox/AppContainer.kt")
    if "val outboxScheduler = OutboxScheduler()" not in container:
        ok = False
        _fail("AppContainer must explicitly wire an OutboxScheduler instance")

    repository = _read("main/java/com/ticketbox/data/repository/OutboxRepository.kt")
    required_repository_tokens = (
        "fun observeStatus(): Flow<OutboxStatus>",
        "data class OutboxStatus",
        "data class OutboxBinding",
        "withBindingTransition",
        "bindingTransitionLease.withLock",
    )
    for token in required_repository_tokens:
        if token not in repository:
            ok = False
            _fail(f"OutboxRepository missing contract token: {token}")

    entity = _read("main/java/com/ticketbox/data/local/PendingMutationEntity.kt")
    required_entity_tokens = (
        '@ColumnInfo(name = "serverUrl", defaultValue = "")',
        '@ColumnInfo(name = "ledgerId", defaultValue = "")',
        'Index(value = ["serverUrl", "ledgerId", "createdAt"])',
        'Index(value = ["serverUrl", "ledgerId", "targetId", "status"])',
        'Index(value = ["serverUrl", "ledgerId", "status"])',
    )
    for token in required_entity_tokens:
        if token not in entity:
            ok = False
            _fail(f"PendingMutationEntity missing binding-scope token: {token}")

    dao = _read("main/java/com/ticketbox/data/local/PendingMutationDao.kt")
    required_dao_tokens = (
        "fun nextRunnableBatch",
        "WHERE pm.serverUrl = :serverUrl",
        "AND pm.ledgerId = :ledgerId",
        "WHERE serverUrl = :serverUrl",
        "AND ledgerId = :ledgerId",
        "NOT EXISTS (",
        "sib.serverUrl = pm.serverUrl",
        "older.ledgerId = pm.ledgerId",
        "older.targetId = pm.targetId",
        "LIMIT :limit",
    )
    for token in required_dao_tokens:
        if token not in dao:
            ok = False
            _fail(f"PendingMutationDao nextRunnableBatch missing token: {token}")

    tests = _read("test/java/com/ticketbox/data/repository/OutboxRepositoryTest.kt")
    required_test_tokens = (
        "dequeueDedupesSameTargetBeforeApplyingLimit",
        "bindingScopedQueueDoesNotDrainRowsFromPreviousLedger",
        "observeStatusAggregatesCurrentBindingOnly",
        "recoverStaleInFlightScopesToCurrentBindingOnly",
        "enqueueWaitsForBindingTransitionAndCannotPersistMixedBinding",
    )
    for token in required_test_tokens:
        if token not in tests:
            ok = False
            _fail(f"OutboxRepositoryTest missing regression test: {token}")

    if ok:
        print("PASS: Android outbox design contract is enforced")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
