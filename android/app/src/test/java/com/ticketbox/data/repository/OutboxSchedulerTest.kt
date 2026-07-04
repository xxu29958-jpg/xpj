package com.ticketbox.data.repository

import androidx.work.BackoffPolicy
import androidx.work.NetworkType
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class OutboxSchedulerTest {

    @Test
    fun periodicRequestPinsConnectivityCadenceBackoffAndWorker() {
        val request = OutboxScheduler.buildPeriodicRequest()
        val spec = request.workSpec

        assertEquals(NetworkType.CONNECTED, spec.constraints.requiredNetworkType)
        assertEquals(
            TimeUnit.MINUTES.toMillis(OutboxScheduler.PERIODIC_INTERVAL_MIN),
            spec.intervalDuration,
        )
        assertEquals(BackoffPolicy.EXPONENTIAL, spec.backoffPolicy)
        assertEquals(
            TimeUnit.SECONDS.toMillis(OutboxScheduler.BACKOFF_MIN_SECONDS),
            spec.backoffDelayDuration,
        )
        assertEquals(OutboxDrainWorker::class.java.name, spec.workerClassName)
        assertTrue(OutboxScheduler.TAG_OUTBOX in request.tags)
    }

    @Test
    fun oneTimeRequestPinsConnectivityBackoffTagAndWorker() {
        val request = OutboxScheduler.buildOneTimeRequest()
        val spec = request.workSpec

        assertEquals(NetworkType.CONNECTED, spec.constraints.requiredNetworkType)
        assertEquals(BackoffPolicy.EXPONENTIAL, spec.backoffPolicy)
        assertEquals(
            TimeUnit.SECONDS.toMillis(OutboxScheduler.BACKOFF_MIN_SECONDS),
            spec.backoffDelayDuration,
        )
        assertEquals(OutboxDrainWorker::class.java.name, spec.workerClassName)
        assertTrue(OutboxScheduler.TAG_OUTBOX in request.tags)
    }

    @Test
    fun uniqueWorkNamesAreStableAndDistinct() {
        assertEquals("ticketbox.outbox.drain.periodic", OutboxScheduler.PERIODIC_WORK_NAME)
        assertEquals("ticketbox.outbox.drain.one_shot", OutboxScheduler.ONE_TIME_WORK_NAME)
        assertTrue(OutboxScheduler.PERIODIC_WORK_NAME != OutboxScheduler.ONE_TIME_WORK_NAME)
    }
}
