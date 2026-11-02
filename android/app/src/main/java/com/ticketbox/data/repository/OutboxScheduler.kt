package com.ticketbox.data.repository

import android.content.Context
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequest
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.UUID
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/**
 * ADR-0038 PR-2g.2 scheduler.
 *
 * Two enqueue surfaces, both keyed by unique-work names so the
 * scheduler is idempotent — call ``ensurePeriodic`` from
 * [com.ticketbox.TicketboxApplication.scheduleStartupWorkersAfterLaunchSettles] and
 * ``enqueueOnce`` from anywhere a fresh mutation lands; WorkManager dedupes:
 *
 *  1. [PERIODIC_WORK_NAME] — the keep-alive heartbeat. Runs every
 *     ~15 minutes (WorkManager's minimum periodic interval, by
 *     contract). A network request buffers ticks while disconnected,
 *     but does not require public-Internet validation: a local Owner
 *     backend can be reachable on a network without Internet access.
 *
 *  2. [ONE_TIME_WORK_NAME] — the immediate trigger. Mutation call
 *     sites invoke [enqueueOnce] after persisting an original intent.
 *     A durable successor covers arrivals after a running worker's
 *     final empty read without cancelling that worker.
 *
 * ``BackoffPolicy.EXPONENTIAL`` with a 30s minimum: after the first
 * [Result.retry], retries land at 30s, 1m, 2m, 4m… up to
 * [androidx.work.WorkRequest.DEFAULT_BACKOFF_DELAY_MILLIS]. This is
 * the engine-level fault path; per-row retries already live inside
 * the drain engine and are independent.
 */
class OutboxScheduler(
    private val workManagerProvider: (Context) -> WorkManager = { context ->
        WorkManager.getInstance(context)
    },
) {
    /**
     * Wire the periodic drain. Safe to call from
     * [com.ticketbox.TicketboxApplication.scheduleStartupWorkersAfterLaunchSettles]
     * after launch has settled. [ExistingPeriodicWorkPolicy.UPDATE]
     * no-ops if the existing schedule matches and adopts the new schedule if
     * the interval / constraints changed across an app upgrade.
     */
    fun ensurePeriodic(context: Context) {
        val wm = workManagerProvider(context)
        wm.enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            // UPDATE means: if a previous schedule exists with the
            // same name but different constraints/interval (app
            // upgrade), replace it. KEEP would let stale schedules
            // linger after we change the interval.
            ExistingPeriodicWorkPolicy.UPDATE,
            buildPeriodicRequest(),
        )
        updateLegacyOneTimeConstraints(wm)
    }

    /**
     * Fire a one-time drain ASAP. The drain still respects
     * network availability — if the device is offline when this
     * is called, the worker queues until a network returns. Mutation
     * call sites call this right after [OutboxRepository.enqueue].
     *
     * [ExistingWorkPolicy.APPEND_OR_REPLACE] preserves a successor even
     * during the final-read/result gap and starts a new chain after cancellation.
     */
    fun enqueueOnce(context: Context) {
        val wm = workManagerProvider(context)
        wm.enqueueUniqueWork(
            ONE_TIME_WORK_NAME,
            ExistingWorkPolicy.APPEND_OR_REPLACE,
            buildOneTimeRequest(),
        )
        updateLegacyOneTimeConstraints(wm)
    }

    /** An old CONNECTED predecessor otherwise blocks every new immediate trigger after upgrade. */
    private fun updateLegacyOneTimeConstraints(wm: WorkManager) {
        val existing = wm.getWorkInfosForUniqueWork(ONE_TIME_WORK_NAME)
        existing.addListener({
            try {
                existing.get().filter {
                    !it.state.isFinished && it.constraints.requiredNetworkRequest == null &&
                        it.constraints.requiredNetworkType == NetworkType.CONNECTED
                }.forEach { info ->
                    // Keep the UUID, enqueue time and dependencies. updateWork never interrupts
                    // an active drain; its new constraints take effect on that worker's next run.
                    val update = wm.updateWork(buildOneTimeRequest(info.id))
                    update.addListener({
                        try {
                            update.get()
                        } catch (error: Exception) {
                            logNetworkWarning("Could not update the legacy outbox schedule", error)
                        }
                    }, completedFutureExecutor)
                }
            } catch (error: Exception) {
                logNetworkWarning("Could not inspect the legacy outbox schedule", error)
            }
        }, completedFutureExecutor)
    }

    /**
     * Cancel both schedules. Used by sign-out flows so a queued
     * worker doesn't try to dispatch against a torn-down session.
     */
    fun cancel(context: Context) {
        val wm = workManagerProvider(context)
        wm.cancelUniqueWork(PERIODIC_WORK_NAME)
        wm.cancelUniqueWork(ONE_TIME_WORK_NAME)
    }

    companion object {
        // Listeners only read already-completed futures and enqueue WorkManager operations.
        private val completedFutureExecutor = Executor { it.run() }
        /**
         * Unique work names. Public so a future maintenance command
         * (e.g. ``adb shell cmd jobscheduler``) can address them and so
         * tests can assert against the same constants.
         */
        const val PERIODIC_WORK_NAME = "ticketbox.outbox.drain.periodic"
        const val ONE_TIME_WORK_NAME = "ticketbox.outbox.drain.one_shot"

        /** Periodic interval per ADR-0038. 15 min is WorkManager's floor. */
        const val PERIODIC_INTERVAL_MIN: Long = 15

        /** Exponential backoff floor after a [Result.retry]. */
        const val BACKOFF_MIN_SECONDS: Long = 30

        /**
         * Tag every outbox WorkRequest with this so a debug tool or
         * future maintenance script can filter just our work.
         */
        const val TAG_OUTBOX = "ticketbox.outbox"

        private fun connectedConstraints(): Constraints =
            Constraints.Builder()
                // minSdk is 28. CONNECTED alone also requires VALIDATED on
                // supported Android versions and can strand local-backend intents.
                // Routing, authentication and reachability remain the HTTP client's job.
                .setRequiredNetworkRequest(
                    NetworkRequest.Builder()
                        .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
                        .build(),
                    NetworkType.CONNECTED,
                )
                .build()

        fun buildPeriodicRequest(): PeriodicWorkRequest =
            PeriodicWorkRequestBuilder<OutboxDrainWorker>(
                PERIODIC_INTERVAL_MIN,
                TimeUnit.MINUTES,
            )
                .setConstraints(connectedConstraints())
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    BACKOFF_MIN_SECONDS,
                    TimeUnit.SECONDS,
                )
                .addTag(TAG_OUTBOX)
                .build()

        fun buildOneTimeRequest(id: UUID = UUID.randomUUID()): OneTimeWorkRequest =
            OneTimeWorkRequestBuilder<OutboxDrainWorker>()
                .setId(id)
                .setConstraints(connectedConstraints())
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    BACKOFF_MIN_SECONDS,
                    TimeUnit.SECONDS,
                )
                .addTag(TAG_OUTBOX)
                .build()
    }
}
