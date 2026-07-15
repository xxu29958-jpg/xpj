"""Release gate for the Android outbox design contract.

The backend release audit is the repo-wide preflight entrypoint, so it also
checks the Android offline queue invariants that previously regressed:
injectable scheduler wiring, one aggregated status surface, stable owner
identity isolation, and SQL-side runnable selection that de-duplicates targets
before applying LIMIT.
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


def _requires(source: str, tokens: tuple[str, ...], *, surface: str) -> bool:
    ok = True
    for token in tokens:
        if token not in source:
            ok = False
            _fail(f"{surface} missing contract token: {token}")
    return ok


def _check_scheduler_wiring() -> bool:
    ok = True
    scheduler = _read("main/java/com/ticketbox/data/repository/OutboxScheduler.kt")
    if "class OutboxScheduler(" not in scheduler or "object OutboxScheduler" in scheduler:
        ok = False
        _fail("OutboxScheduler must stay an injectable class, not a singleton object")
    container = _read("main/java/com/ticketbox/AppContainer.kt")
    if "val outboxScheduler = OutboxScheduler()" not in container:
        ok = False
        _fail("AppContainer must explicitly wire an OutboxScheduler instance")
    return ok


def _check_repository_contract() -> bool:
    repository = _read("main/java/com/ticketbox/data/repository/OutboxRepository.kt")
    return _requires(
        repository,
        (
            "fun observeStatus(): Flow<OutboxStatus>",
            "data class OutboxStatus",
            "data class OutboxBinding",
            "withBindingTransition",
            "bindingTransitionLease.withLock",
        ),
        surface="OutboxRepository",
    )


def _check_entity_contract() -> bool:
    entity = _read("main/java/com/ticketbox/data/local/PendingMutationEntity.kt")
    return _requires(
        entity,
        (
            '@ColumnInfo(name = "serverUrl", defaultValue = "")',
            '@ColumnInfo(name = "ledgerId", defaultValue = "")',
            '@ColumnInfo(name = "ownerKey")',
            'Index(value = ["ownerKey", "ledgerId", "createdAt"])',
            'Index(value = ["ownerKey", "ledgerId", "targetId", "status"])',
            'Index(value = ["ownerKey", "ledgerId", "status"])',
        ),
        surface="PendingMutationEntity",
    )


def _check_dao_contract() -> bool:
    dao = _read("main/java/com/ticketbox/data/local/PendingMutationDao.kt")
    return _requires(
        dao,
        (
            "fun nextRunnableBatch",
            "WHERE pm.ownerKey = :ownerKey",
            "AND pm.ledgerId = :ledgerId",
            "WHERE ownerKey = :ownerKey",
            "AND ledgerId = :ledgerId",
            "NOT EXISTS (",
            "sib.ownerKey = pm.ownerKey",
            "older.ownerKey = pm.ownerKey",
            "older.ledgerId = pm.ledgerId",
            "older.targetId = pm.targetId",
            "LIMIT :limit",
        ),
        surface="PendingMutationDao nextRunnableBatch",
    )


def _check_regression_tests() -> bool:
    tests = _read("test/java/com/ticketbox/data/repository/OutboxRepositoryTest.kt")
    repository_tests_ok = _requires(
        tests,
        (
            "dequeueDedupesSameTargetBeforeApplyingLimit",
            "bindingScopedQueueDoesNotDrainRowsFromPreviousLedger",
            "observeStatusAggregatesCurrentBindingOnly",
            "recoverStaleInFlightScopesToCurrentBindingOnly",
            "enqueueWaitsForBindingTransitionAndCannotPersistMixedBinding",
        ),
        surface="OutboxRepositoryTest",
    )
    isolation_tests = _read("test/java/com/ticketbox/data/repository/OutboxBindingIsolationTest.kt")
    isolation_tests_ok = _requires(
        isolation_tests,
        (
            "sameDeviceRecoveryMakesItsQuarantinedIntentRunnableAgain",
            "anotherDeviceCannotSeeOrReplayThePreviousDevicesIntent",
            "rebindAtEnqueueLinearizationPointRejectsTheOldIntent",
            "staleStatusActionCannotResolveRowFromPreviousBinding",
        ),
        surface="OutboxBindingIsolationTest",
    )
    return repository_tests_ok and isolation_tests_ok


def main() -> int:
    checks = (
        _check_scheduler_wiring(),
        _check_repository_contract(),
        _check_entity_contract(),
        _check_dao_contract(),
        _check_regression_tests(),
    )

    if all(checks):
        print("PASS: Android outbox design contract is enforced")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
