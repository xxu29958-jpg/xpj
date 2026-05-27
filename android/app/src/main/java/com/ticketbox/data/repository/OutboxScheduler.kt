package com.ticketbox.data.repository

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * ADR-0038 PR-2g.2 scheduler.
 *
 * Two enqueue surfaces, both keyed by unique-work names so the
 * scheduler is idempotent — call ``ensurePeriodic`` from
 * [com.ticketbox.TicketboxApplication.onCreate] and ``enqueueOnce``
 * from anywhere a fresh mutation lands; WorkManager dedupes:
 *
 *  1. [PERIODIC_WORK_NAME] — the keep-alive heartbeat. Runs every
 *     ~15 minutes (WorkManager's minimum periodic interval, by
 *     contract). [NetworkType.CONNECTED] ensures the OS buffers the
 *     tick across offline stretches: if the device is offline at
 *     the scheduled time, the next tick fires the moment network
 *     returns, which is exactly the "drain on connectivity-up"
 *     contract from ADR-0038.
 *
 *  2. [ONE_TIME_WORK_NAME] — the immediate trigger. Future PR-2g.3
 *     call sites will invoke [enqueueOnce] right after enqueueing
 *     a new outbox row, so the user doesn't wait up to 15 min for
 *     the periodic tick. ``KEEP`` policy means a second call while
 *     a one-time worker is already queued is a no-op — no
 *     thundering herd if 20 rows are enqueued in a burst.
 *
 * ``BackoffPolicy.EXPONENTIAL`` with a 30s minimum: after the first
 * [Result.retry], retries land at 30s, 1m, 2m, 4m… up to
 * [androidx.work.WorkRequest.DEFAULT_BACKOFF_DELAY_MILLIS]. This is
 * the engine-level fault path; per-row retries already live inside
 * the drain engine and are independent.
 */
object OutboxScheduler {
    /**
     * Unique work names. Public so a future maintenance command
     * (e.g. ``adb shell cmd jobscheduler``) can address them and so
     * tests can assert against the same constants.
     */
    const val PERIODIC_WORK_NAME = "ticketbox.outbox.drain.periodic"
    const val ONE_TIME_WORK_NAME = "ticketbox.outbox.drain.one_shot"

    /** Periodic interval per ADR-0038. 15 min is WorkManager's floor. */
    val PERIODIC_INTERVAL_MIN: Long = 15

    /** Exponential backoff floor after a [Result.retry]. */
    val BACKOFF_MIN_SECONDS: Long = 30

    /**
     * Wire the periodic drain. Safe to call from
     * [com.ticketbox.TicketboxApplication.onCreate] on every cold
     * start — [ExistingPeriodicWorkPolicy.UPDATE] no-ops if the
     * existing schedule matches and adopts the new schedule if the
     * interval / constraints changed across an app upgrade.
     */
    fun ensurePeriodic(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = PeriodicWorkRequestBuilder<OutboxDrainWorker>(
            PERIODIC_INTERVAL_MIN,
            TimeUnit.MINUTES,
        )
            .setConstraints(constraints)
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                BACKOFF_MIN_SECONDS,
                TimeUnit.SECONDS,
            )
            .addTag(TAG_OUTBOX)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            // UPDATE means: if a previous schedule exists with the
            // same name but different constraints/interval (app
            // upgrade), replace it. KEEP would let stale schedules
            // linger after we change the interval.
            ExistingPeriodicWorkPolicy.UPDATE,
            request,
        )
    }

    /**
     * Fire a one-time drain ASAP. The drain still respects
     * [NetworkType.CONNECTED] — if the device is offline when this
     * is called, the worker queues until network returns. Future
     * call sites (PR-2g.3) call this right after
     * [OutboxRepository.enqueue].
     *
     * [ExistingWorkPolicy.KEEP] makes back-to-back calls
     * idempotent: a burst of 20 enqueues during one connectivity
     * window collapses into a single drain pass.
     */
    fun enqueueOnce(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val request = OneTimeWorkRequestBuilder<OutboxDrainWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                BACKOFF_MIN_SECONDS,
                TimeUnit.SECONDS,
            )
            .addTag(TAG_OUTBOX)
            .build()

        WorkManager.getInstance(context).enqueueUniqueWork(
            ONE_TIME_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }

    /**
     * Cancel both schedules. Used by sign-out flows so a queued
     * worker doesn't try to dispatch against a torn-down session.
     */
    fun cancel(context: Context) {
        val wm = WorkManager.getInstance(context)
        wm.cancelUniqueWork(PERIODIC_WORK_NAME)
        wm.cancelUniqueWork(ONE_TIME_WORK_NAME)
    }

    /**
     * Tag every outbox WorkRequest with this so a debug tool or
     * future maintenance script can filter just our work.
     */
    const val TAG_OUTBOX = "ticketbox.outbox"
}
