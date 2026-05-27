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
        var discarded = 0
        var skipped = 0
        for (row in batch) {
            val dispatcher = registry[row.type]
            if (dispatcher == null || row.type == PendingMutationType.Unknown) {
                skipped++
                continue
            }
            outbox.markInFlight(row.id)
            when (val result = runCatching { dispatcher.dispatch(row) }.getOrElse {
                DispatchResult.Failure(it.message ?: "dispatch threw")
            }) {
                DispatchResult.Success -> {
                    outbox.markDone(row.id)
                    done++
                }
                is DispatchResult.Conflict -> {
                    outbox.markConflict(row.id, result.serverMessage)
                    conflicts++
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
            discarded = discarded,
            skipped = skipped,
        )
    }
}

data class DrainSummary(
    val attempted: Int,
    val done: Int,
    val conflicts: Int,
    val failures: Int,
    val discarded: Int,
    val skipped: Int,
) {
    val anythingChanged: Boolean
        get() = done > 0 || conflicts > 0 || failures > 0 || discarded > 0

    companion object {
        val IDLE = DrainSummary(0, 0, 0, 0, 0, 0)
    }
}
