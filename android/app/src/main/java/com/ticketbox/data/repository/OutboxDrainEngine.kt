package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

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
 *    types with no registered dispatcher are marked FAILED with
 *    ``no_dispatcher_registered:<wireType>`` (codex round-1 P2#5).
 *    They leave the PENDING queue so newer same-or-later rows
 *    can proceed; the user clears them via
 *    [OutboxRepository.resolveFailed] (Retry after app upgrade
 *    that supplies the missing dispatcher, or Drop).
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
     *
     * Sweeps stale IN_FLIGHT rows (left behind by a cancelled or
     * crashed worker) back to PENDING before dequeueing so the
     * same-target dedup doesn't permanently block siblings.
     * [codex round-2 P1#2] companion.
     */
    suspend fun drainOnce(): DrainSummary {
        // v9 → v10 one-time backfill: adopt any rows the schema migration left
        // with an empty binding into the current one before the binding-scoped
        // reads run, so pre-upgrade offline edits aren't stranded. No-op once
        // adopted / while unbound.
        outbox.adoptLegacyRowsForCurrentBinding()
        outbox.recoverStaleInFlight()
        // [codex round-9 P1] session-boundary epoch: capture the
        // counter BEFORE dequeue. A binding transition between this snapshot
        // and the dispatch loop will bump the counter; the post-claim
        // check below will see it and abort the rest of the batch
        // before any in-memory row is sent under the new session.
        val capturedEpoch = outbox.currentSessionEpoch()
        val batch = outbox.dequeueNextRunnable()
        if (batch.isEmpty()) return DrainSummary.IDLE

        var done = 0
        var conflicts = 0
        var failures = 0
        var retryable = 0
        var discarded = 0
        var unsupported = 0
        var raced = 0
        var aborted = 0
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
            // [codex round-10 P1] Hold the dispatch lease across
            // BOTH the epoch check AND the dispatcher.dispatch(row)
            // call. Without the lease, a binding transition that fires
            // AFTER the epoch check but BEFORE dispatch resolves
            // apiProvider() / OkHttp reads the token would let the
            // old row be sent under the NEW session. With the
            // lease:
            //   - the binding transition blocks until our dispatch returns,
            //   - credentials writes happen inside that locked transition,
            //   - so dispatcher.dispatch(row) always sees the
            //     credentials it was queued under.
            //
            // ``signalAbort = true`` returned from inside the
            // lease means "epoch check failed, abort the remainder
            // of the batch". We propagate that up after the lease
            // releases so the abort accounting reads the same
            // counters the dispatch result handlers updated.
            val signalAbort = outbox.withDispatchLease {
                // [codex round-9 P1] post-claim epoch check.
                // Binding transition bumps the epoch before credentials
                // change;
                // if the epoch changed between our snapshot and the
                // moment we acquired the lease, the row was loaded under
                // a stale binding and must not dispatch under whatever
                // session the user just bound. Abort the rest of the
                // batch.
                if (outbox.currentSessionEpoch() != capturedEpoch) {
                    return@withDispatchLease true
                }
                // [codex round-2 P1#2] fix: do NOT let runCatching
                // swallow CancellationException — that would let a
                // structured-concurrency cancel mark the row as
                // RetryableFailure mid-shutdown. Catch it
                // explicitly and roll the row back to PENDING in a
                // NonCancellable context so a fresh drain can
                // re-claim it after the worker restarts.
                val result = try {
                    dispatcher.dispatch(row)
                } catch (e: CancellationException) {
                    withContext(NonCancellable) {
                        outbox.markRetryable(row.id, "drain cancelled mid-dispatch")
                    }
                    throw e
                } catch (e: Exception) {
                    // [codex round-5 P3] catch Exception, not
                    // Throwable — Error subclasses (OOM, Linkage,
                    // StackOverflow, VirtualMachineError) indicate
                    // JVM-level damage that the per-row retry
                    // policy can't recover from; let them propagate
                    // up to the worker so WorkManager's own restart
                    // semantics handle it. CancellationException is
                    // already taken by the catch above (it extends
                    // Exception, but the more-specific catch binds
                    // first).
                    DispatchResult.RetryableFailure(e.message ?: "dispatch threw")
                }
                when (result) {
                    is DispatchResult.Success -> {
                        outbox.markDone(row.id)
                        // [codex finding P1#1] fix: cascade the
                        // server's post-mutation token to same-
                        // target PENDING rows so the next chained
                        // mutation against this row doesn't replay
                        // with a now-stale snapshot.
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
                        // [codex finding P1#3] fix: keep the row
                        // in PENDING so the next drain tick picks
                        // it up. The retryCount was already bumped
                        // by tryClaim; the scheduler can apply
                        // back-off based on it.
                        outbox.markRetryable(row.id, result.message)
                        retryable++
                    }
                    is DispatchResult.Failure -> {
                        outbox.markFailed(row.id, result.message)
                        failures++
                    }
                    is DispatchResult.Discarded -> {
                        // Discarded rows are gone from the user's
                        // view — there's nothing for them to
                        // resolve. Mark DONE and let cleanup
                        // garbage-collect after retention.
                        outbox.markDone(row.id)
                        discarded++
                    }
                }
                false  // not aborting
            }
            if (signalAbort) {
                val processed = done + conflicts + failures + retryable +
                    discarded + unsupported + raced
                aborted = batch.size - processed
                break
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
            aborted = aborted,
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
    /**
     * [codex round-9 P1] rows in the batch that were skipped
     * because a session boundary ([OutboxRepository.withBindingTransition])
     * fired mid-drain. The in-memory copies were loaded under the
     * old binding, so the drain aborted the remaining batch.
     */
    val aborted: Int = 0,
) {
    val anythingChanged: Boolean
        get() = done > 0 || conflicts > 0 || failures > 0 ||
            retryable > 0 || discarded > 0 || unsupported > 0

    companion object {
        val IDLE = DrainSummary(0, 0, 0, 0)
    }
}
