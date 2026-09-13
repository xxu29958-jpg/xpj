package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.sync.withLock
import java.time.Instant

/**
 * Drain and completion marks for [OutboxRepository].
 * Same-package physical move so the repository class stays under the LargeClass gate.
 */

/**
 * Return the next runnable batch in causal order. Three filters:
 *
 * 1. Skip rows whose target has ANY unresolved sibling row —
 *    IN_FLIGHT (another drain is running it), CONFLICT (user
 *    hasn't picked keep/drop yet), or FAILED (waiting for
 *    manual retry or dismissal). [codex round-2 P1#1] fix:
 *    the old "only block on IN_FLIGHT" let a queued B sneak
 *    past a CONFLICT A and either fake-conflict or apply on
 *    top of an un-resolved state.
 * 2. Within the returned batch, keep only the OLDEST PENDING
 *    row per target. This is the [codex round-1 P1#1] fix —
 *    without per-target dedup, the same drain pass would
 *    return both A and B for ``expense:1`` and the engine
 *    would dispatch them in parallel even though
 *    ``markInFlightIfPending`` is per-row atomic. The DAO now
 *    also applies this same-target filter before ``LIMIT`` so
 *    duplicate targets do not consume the whole batch.
 * 3. Returns the public [OutboxRow] view (not the raw Entity)
 *    so the drain engine doesn't depend on Room types.
 */
suspend fun OutboxRepository.dequeueNextRunnable(limit: Int = OutboxRepository.DEFAULT_DRAIN_BATCH, excludedIds: List<Long> = emptyList()): List<OutboxRow> {
    val binding = currentBinding()
    // [codex round-3 P2#1 / round-4 P1] Use the SQL-side filter
    // so LIMIT applies AFTER unresolved targets are excluded.
    // Round-3 introduced ``nextRunnableBatch`` but a rebase wiped
    // out the production caller; round-4 wires it back.
    val candidates = dao.nextRunnableBatch(
        ownerKey = binding.ownerStorageKey,
        ledgerId = binding.ledgerId,
        unresolvedStatuses = OutboxRepository.UNRESOLVED_STATUS_VALUES,
        limit = limit,
        excludedIds = excludedIds,
    )
    if (candidates.isEmpty()) return emptyList()
    val seenTargets = mutableSetOf<String>()
    val runnable = mutableListOf<OutboxRow>()
    for (row in candidates) {
        if (!seenTargets.add(row.targetId)) {
            // An older PENDING row for this target is already
            // in the batch; the second one waits for the next
            // drain pass to keep "same target serial".
            continue
        }
        runnable += row.toDomain()
    }
    return runnable
}

/**
 * Recovery: push rows stuck in IN_FLIGHT past [staleAfterMillis]
 * back to PENDING so the next drain can re-claim them. Called
 * by the engine at the start of each drain.
 *
 * [codex round-2 P1#2] fix: a CancellationException after
 * ``tryClaim`` succeeded leaves the row IN_FLIGHT; without
 * this sweep ``hasUnresolvedRowForTarget`` then blocks every
 * later sibling forever.
 */
suspend fun OutboxRepository.recoverStaleInFlight(staleAfterMillis: Long = OutboxRepository.DEFAULT_STALE_IN_FLIGHT_MS): Int {
    val cutoff = Instant.now(clock).minusMillis(staleAfterMillis)
    return currentBinding().let { binding ->
        dao.recoverStaleInFlight(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            staleCutoffIso = OutboxRepository.ISO.format(cutoff),
            recoveryMessage = "recovered_from_stuck_in_flight",
        )
    }
}

/**
 * Atomic PENDING → IN_FLIGHT claim. Returns ``true`` if this
 * caller won the race and is now responsible for dispatching;
 * ``false`` means another drain pass already claimed it and
 * the caller must NOT call the ApiService.
 */
suspend fun OutboxRepository.tryClaim(id: Long): Boolean {
    val rowcount = dao.markInFlightIfPending(
        id = id,
        fromStatus = PendingMutationStatus.Pending.wireValue,
        inFlightStatus = PendingMutationStatus.InFlight.wireValue,
        attemptedAt = nowIso(),
    )
    return rowcount > 0
}
suspend fun OutboxRepository.markDone(id: Long, cacheRefreshVersion: Long? = null, receiptJson: String? = null) {
    dao.markDone(
        id = id,
        status = PendingMutationStatus.Done.wireValue,
        completedAt = nowIso(),
        lastError = cacheRefreshVersion?.let { "$EXPENSE_REFRESH_PREFIX$it" },
        receiptJson = receiptJson,
    )
}

/** Acknowledges adopted roots without changing delivery, original OCC or command bytes. */
internal suspend fun OutboxRepository.acknowledgeExpenseRefresh(boundRequest: BoundLedgerRequest, versions: Map<Long, Long>) =
    bindingTransitionLease.withLock {
        val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
        try {
            boundRequest.requireStillActiveFor(binding)
        } catch (_: RepositoryException) {
            // Adoption already completed. A later transition leaves its marker for the next bound read.
            return@withLock
        }
        dao.clearAdoptedExpenseRefreshes(binding, versions)
    }

/**
 * Cascade a freshly-server-returned token to every PENDING row
 * targeting the same row. See
 * [PendingMutationDao.cascadeFreshTokenForTarget] for the why.
 *
 * Returns the count of cascaded rows for tests / telemetry.
 */
suspend fun OutboxRepository.cascadeFreshToken(targetId: String, newToken: Long): Int =
    currentBinding().let { binding ->
        dao.cascadeFreshTokenForTarget(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            targetId = targetId,
            preservedTokenTypes = listOf(PendingMutationType.UndoExpense.wireValue, PendingMutationType.VoidExpenseOffset.wireValue,
                PendingMutationType.CreateBillSplitInvitation.wireValue,
                PendingMutationType.CorrectExpense.wireValue, PendingMutationType.CreateExpenseOffset.wireValue, PendingMutationType.UploadScreenshot.wireValue),
            freshToken = newToken,
        )
    }

/**
 * Transient failure: keep the row in PENDING so the next drain
 * pass picks it up. ``retryCount`` was already bumped by
 * [tryClaim]; back-off is scheduler-side, but **give-up is engine-side**:
 * [OutboxDrainEngine] checks ``row.retryCount + 1 >= maxAttempts`` in the
 * RetryableFailure branch and routes to [markFailed] instead of
 * [markRetryable] once the cap trips (codex P1 #7).
 */
suspend fun OutboxRepository.markRetryable(id: Long, error: String) {
    dao.markRetryable(
        id = id,
        pendingStatus = PendingMutationStatus.Pending.wireValue,
        lastError = error,
    )
}

/**
 * codex P2 #10 follow-up: revert a [tryClaim] that aborted before any actual
 * dispatch ran. Undoes the retryCount bump + attemptedAt set so an epoch-abort
 * or mid-dispatch cancellation 不算一次"尝试", 避免 session 反复 flap N 次后
 * max_attempts 假性触发。
 *
 * `internal` 因为只该 engine 用; DAO 也带 `AND status = :inFlightStatus` 守卫,
 * 即使被外部误调也只对 IN_FLIGHT row 起效。
 */
internal suspend fun OutboxRepository.revertClaimWithoutAttempt(id: Long) {
    dao.revertClaimWithoutAttempt(
        id = id,
        pendingStatus = PendingMutationStatus.Pending.wireValue,
        inFlightStatus = PendingMutationStatus.InFlight.wireValue,
    )
}

suspend fun OutboxRepository.markConflict(id: Long, serverMessage: String) {
    dao.markConflict(
        id = id,
        status = PendingMutationStatus.Conflict.wireValue,
        lastError = serverMessage,
    )
}

/**
 * Move a row to terminal FAILED. ``retryCount`` is **NOT** reset here — the
 * historical attempt count survives so observability / debug surfaces can
 * read it (codex P1 #7). Once the user picks
 * [FailedResolution.Retry][FailedResolution.Retry], the DAO atomic update
 * (`retryFailed` / `requeueFailedWithFreshToken`) zeros it so they get a
 * fresh budget. While the row is FAILED, ``retryCount`` should be treated
 * as historical-only — no future drain decision keys off it.
 */
suspend fun OutboxRepository.markFailed(id: Long, error: String, blocksFollowing: Boolean = true) {
    dao.markFailed(
        id = id,
        status = PendingMutationStatus.Failed.wireValue,
        lastError = error,
        blocksFollowing = blocksFollowing,
    )
}
/**
 * ADR-0042 §4.10 reaper: terminally FAIL every PENDING row enqueued more than
 * [OUTBOX_PENDING_AGE_CAP_MILLIS] ago WITHOUT replaying it, and return how
 * many rows were reaped.
 *
 * The drain engine calls this at the start of every pass. A row that's been
 * PENDING past the cap can no longer rely on its idempotency key (the server
 * has likely purged it — see [OUTBOX_PENDING_AGE_CAP_MILLIS]), so replaying it
 * risks a double-apply. Flipping it to FAILED here means [dequeueNextRunnable]
 * will never hand it to a dispatcher; instead it surfaces in the
 * "manual retry / drop" banner via [observeStatus] with the
 * ``outbox_row_expired`` marker, and the user redoes the action by hand
 * against fresh server state.
 *
 * **Global, not binding-scoped** (unlike the drain reads): a stale PENDING row
 * under ANY binding becomes a double-apply risk as soon as that binding is
 * active again, so the reap intentionally ignores ``serverUrl`` / ``ledgerId``
 * — same global reach as [gcCompleted] / [clearAll]. The DAO's
 * ``status = 'pending'`` guard keeps it from touching IN_FLIGHT / CONFLICT /
 * FAILED / DONE rows.
 *
 * [nowMillis] is injected (the engine passes its lambda clock) so the cap can
 * be exercised deterministically in a JVM unit test.
 *
 * @return the number of expired PENDING rows reaped to FAILED.
 */
suspend fun OutboxRepository.reapExpiredPending(nowMillis: Long): Int {
    val cutoff = Instant.ofEpochMilli(nowMillis - OUTBOX_PENDING_AGE_CAP_MILLIS)
    return dao.markExpiredPendingAsFailed(
        cutoffCreatedAtIso = OutboxRepository.ISO.format(cutoff),
        status = PendingMutationStatus.Failed.wireValue,
        // Structured marker (snake_case, like recovered_from_stuck_in_flight /
        // no_dispatcher_registered:): SyncStatusScreen.friendlyLastError maps it
        // to user-facing copy. Never the raw key/timestamp — §10 jargon rule.
        lastError = "outbox_row_expired",
    )
}

