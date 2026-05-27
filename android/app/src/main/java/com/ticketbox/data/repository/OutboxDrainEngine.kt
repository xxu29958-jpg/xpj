package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType

/**
 * ADR-0038 PR-2g drain engine.
 *
 * Pure orchestration: dequeue → dispatch → status transition. The
 * engine itself is unit-testable on the JVM — no Android primitives,
 * no WorkManager. PR-2g.2 will wire a WorkManager-backed scheduler
 * that triggers [drainOnce] on connectivity-up + a periodic tick;
 * PR-2g.3 will route the mutation call sites through the outbox so
 * actual rows land in the queue.
 *
 * Invariants the engine preserves:
 * 1. Dequeue order is causal (``createdAt`` ASC) — guaranteed by
 *    [OutboxRepository.dequeueNextRunnable].
 * 2. Same target serial — also guaranteed by the repository.
 * 3. Each row gets exactly one in-flight ApiService call per
 *    [drainOnce] invocation; status transitions persist before the
 *    next row is dequeued, so a crash mid-drain leaves the queue
 *    in a consistent state on restart.
 * 4. Unknown mutation types ([PendingMutationType.Unknown]) and
 *    types with no registered dispatcher are left in PENDING (the
 *    app might be running an older build than the queued mutation;
 *    log + skip rather than drop).
 */
class OutboxDrainEngine(
    private val outbox: OutboxRepository,
    dispatchers: Iterable<OutboxMutationDispatcher>,
) {
    private val registry: Map<PendingMutationType, OutboxMutationDispatcher> =
        dispatchers.associateBy { it.type }

    /**
     * Replay every currently-runnable row exactly once. Returns the
     * summary so the caller (worker / UI / tests) can decide whether
     * to re-enqueue itself.
     */
    suspend fun drainOnce(): DrainSummary {
        val batch = outbox.dequeueNextRunnable()
        if (batch.isEmpty()) return DrainSummary.IDLE

        var done = 0
        var conflicts = 0
        var failures = 0
        var retryable = 0
        var discarded = 0
        var unsupported = 0
        var raced = 0
        for (row in batch) {
            val dispatcher = registry[row.type]
            if (dispatcher == null || row.type == PendingMutationType.Unknown) {
                // [codex finding P2#5] fix: rows with no registered
                // dispatcher used to stay PENDING forever, blocking
                // newer same-or-later rows behind them in the
                // ``ORDER BY createdAt`` window. Move them to FAILED
                // with a structured ``lastError`` so a UI affordance
                // can offer "upgrade the app, then manual retry" or
                // "drop". The user-visible behaviour is identical to
                // a 4xx that needs human action.
                outbox.markFailed(row.id, "no_dispatcher_registered:${row.type.wireValue}")
                unsupported++
                continue
            }
            // [codex finding P1#2] fix: atomic PENDING → IN_FLIGHT
            // claim. If another drain pass beat us to it, the
            // dispatcher MUST NOT be called.
            if (!outbox.tryClaim(row.id)) {
                raced++
                continue
            }
            when (val result = runCatching { dispatcher.dispatch(row) }.getOrElse {
                DispatchResult.RetryableFailure(it.message ?: "dispatch threw")
            }) {
                is DispatchResult.Success -> {
                    outbox.markDone(row.id)
                    // [codex finding P1#1] fix: cascade the server's
                    // post-mutation token to same-target PENDING
                    // rows so the next chained mutation against this
                    // row doesn't replay with a now-stale snapshot.
                    val newToken = result.newUpdatedAt
                    if (!newToken.isNullOrEmpty()) {
                        outbox.cascadeFreshToken(row.targetId, newToken)
                    }
                    done++
                }
                is DispatchResult.Conflict -> {
                    outbox.markConflict(row.id, result.serverMessage)
                    conflicts++
                }
                is DispatchResult.RetryableFailure -> {
                    // [codex finding P1#3] fix: keep the row in
                    // PENDING so the next drain tick picks it up.
                    // The retryCount was already bumped by tryClaim;
                    // the scheduler can apply back-off based on it.
                    outbox.markRetryable(row.id, result.message)
                    retryable++
                }
                is DispatchResult.Failure -> {
                    outbox.markFailed(row.id, result.message)
                    failures++
                }
                is DispatchResult.Discarded -> {
                    // Discarded rows are gone from the user's view —
                    // there's nothing for them to resolve. Mark DONE
                    // and let cleanup garbage-collect after retention.
                    outbox.markDone(row.id)
                    discarded++
                }
            }
        }
        return DrainSummary(
            attempted = batch.size,
            done = done,
            conflicts = conflicts,
            failures = failures,
            retryable = retryable,
            discarded = discarded,
            unsupported = unsupported,
            raced = raced,
        )
    }
}

data class DrainSummary(
    val attempted: Int,
    val done: Int,
    val conflicts: Int,
    val failures: Int,
    /** Transient failure — row stayed PENDING for the next drain. */
    val retryable: Int = 0,
    val discarded: Int = 0,
    /** No dispatcher registered for the row's type → markFailed. */
    val unsupported: Int = 0,
    /** Atomic claim lost a race with a concurrent drain. */
    val raced: Int = 0,
) {
    val anythingChanged: Boolean
        get() = done > 0 || conflicts > 0 || failures > 0 ||
            retryable > 0 || discarded > 0 || unsupported > 0

    companion object {
        val IDLE = DrainSummary(0, 0, 0, 0)
    }
}
