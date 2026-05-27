package com.ticketbox.data.repository

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CancellationException

/**
 * ADR-0038 PR-2g.2: WorkManager-backed worker that hands a single
 * drain pass to [OutboxDrainEngine].
 *
 * Why a CoroutineWorker rather than a Service or a plain background
 * coroutine:
 * - Survives process death: the OS persists WorkRequests on disk
 *   and re-issues them after a kill / restart, so a queued outbox
 *   row keeps draining even if the user force-stops the app and
 *   returns later.
 * - Network constraint piggy-back: the periodic schedule attaches
 *   ``NetworkType.CONNECTED``, so the OS implicitly buffers the
 *   tick across offline windows — we don't need a custom
 *   connectivity listener for the "drain on connectivity-up"
 *   contract that ADR-0038 calls out.
 * - Backoff is built-in: when [doWork] returns
 *   [Result.retry], WorkManager applies exponential backoff
 *   (capped via [androidx.work.WorkRequest.MIN_BACKOFF_MILLIS])
 *   and re-runs the worker — no per-row retry math in our code.
 *
 * Why the worker reaches into [TicketboxApplication.container]
 * instead of accepting an [OutboxDrainEngine] via constructor
 * injection: the app uses manual DI ([com.ticketbox.AppContainer]);
 * WorkManager's default WorkerFactory only knows
 * ``(Context, WorkerParameters)``. A custom WorkerFactory is the
 * standard escape hatch but is heavier than the runtime lookup
 * pattern and would have to live in this PR ahead of any other
 * Workers existing. We adopt the heavier pattern only when a
 * second Worker arrives.
 *
 * The doWork contract:
 *  - Queue idle OR at least one row moved forward → SUCCESS.
 *  - All attempted rows came back [DispatchResult.RetryableFailure]
 *    → RETRY (WorkManager applies backoff and re-enqueues).
 *  - The worker never returns FAILURE on a per-row error — failed
 *    rows are surfaced via the outbox repository's
 *    ``observeFailed`` flow, NOT as worker-level failures.
 *    WorkManager FAILURE would suppress retries for the WHOLE drain
 *    on the OS side, which is wrong when one row is dead but ten
 *    others are healthy and waiting.
 */
class OutboxDrainWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as? TicketboxApplication)?.container
            ?: run {
                // Defensive: the worker should never run before
                // Application.onCreate. If it does, the OS will
                // reschedule us anyway when the app boots.
                Log.w(TAG, "AppContainer not yet ready; deferring drain")
                return Result.retry()
            }
        val outcome = runDrain(
            logWarning = { message, error -> Log.w(TAG, message, error) },
        ) { container.outboxDrainEngine.drainOnce() }
        return when (outcome) {
            DrainOutcome.SUCCESS -> Result.success()
            DrainOutcome.RETRY -> Result.retry()
        }
    }

    /**
     * Internal post-drain classification. Extracted from the
     * Android-bound [doWork] so unit tests can verify the
     * [DrainSummary] → [DrainOutcome] mapping in pure JVM without
     * pulling Robolectric in for one binding.
     */
    internal enum class DrainOutcome { SUCCESS, RETRY }

    companion object {
        const val TAG = "OutboxDrainWorker"

        /**
         * Runs the given drain operation and maps its outcome onto
         * a WorkManager-equivalent [DrainOutcome].
         *
         * Two seams keep this testable in pure JVM:
         *
         *  - ``drain`` is passed in as a ``suspend () -> DrainSummary``
         *    lambda. Taking a lambda rather than the engine instance
         *    decouples this function from [OutboxDrainEngine] being
         *    ``final`` (the engine has no polymorphic responsibility),
         *    and lets unit tests inject arbitrary summary / exception
         *    shapes without a fake subclass.
         *
         *  - ``logWarning`` is the only Android-bound side effect the
         *    drain policy has on the failure path; it's injected so
         *    unit tests can default to a no-op while
         *    [OutboxDrainWorker.doWork] supplies the real
         *    [android.util.Log.w] binding. The previous version called
         *    ``Log.w`` directly here, which is a classic JVM unit-test
         *    trap — ``android.util.Log`` is an unmocked stub and any
         *    call throws ``RuntimeException("Method w in android.util
         *    .Log not mocked.")`` from the failing-engine branch,
         *    masquerading as the original exception. Splitting the
         *    logger out keeps this function pure policy and the worker
         *    the only thing touching the Android SDK.
         */
        internal suspend fun runDrain(
            logWarning: (String, Throwable) -> Unit = { _, _ -> },
            drain: suspend () -> DrainSummary,
        ): DrainOutcome {
            val summary: DrainSummary = try {
                drain()
            } catch (e: CancellationException) {
                // The engine itself rolls in-flight rows back to
                // PENDING via NonCancellable inside the cancellation
                // path (OutboxDrainEngine round-2 P1#2). Rethrow so
                // WorkManager treats this as a graceful cancellation
                // rather than counting it as a backoff cycle.
                throw e
            } catch (e: Exception) {
                // Engine-level fault (DB corruption, etc.). Returning
                // RETRY lets the OS apply backoff; the next tick re-
                // tries from a clean dequeue. We don't return FAILURE
                // — that would suppress retries permanently for the
                // WHOLE drain, which is too blunt for a transient
                // engine fault.
                logWarning("drainOnce threw, will retry", e)
                return DrainOutcome.RETRY
            }
            return classify(summary)
        }

        internal fun classify(summary: DrainSummary): DrainOutcome =
            when {
                // Idle queue → nothing for us to do; the periodic
                // tick fires again on schedule.
                summary.attempted == 0 -> DrainOutcome.SUCCESS

                // Mixed-outcome batch — at least one row resolved
                // (done / conflict / failed / discarded / unsupported).
                // SUCCESS so the next periodic tick starts fresh
                // rather than waiting out a backoff window.
                summary.done > 0 ||
                    summary.conflicts > 0 ||
                    summary.failures > 0 ||
                    summary.discarded > 0 ||
                    summary.unsupported > 0 -> DrainOutcome.SUCCESS

                // Pure transient-failure batch (every row came back
                // RetryableFailure). Tell WorkManager to back off;
                // no point firing again immediately when the
                // underlying network blip hasn't recovered.
                summary.retryable > 0 -> DrainOutcome.RETRY

                // All-raced (every row lost the atomic claim to a
                // concurrent drain). Treat as SUCCESS; the winning
                // drain handled them.
                else -> DrainOutcome.SUCCESS
            }
    }
}
