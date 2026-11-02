package com.ticketbox.data.repository

import android.app.Application
import android.net.NetworkCapabilities
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [28, 35])
class OutboxSchedulerTest {

    @Test
    fun periodicRequestPinsConnectivityCadenceBackoffAndWorker() {
        val request = OutboxScheduler.buildPeriodicRequest()
        val spec = request.workSpec

        assertLocalBackendNetworkRequirements(spec.constraints)
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

        assertLocalBackendNetworkRequirements(spec.constraints)
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

    private fun assertLocalBackendNetworkRequirements(constraints: Constraints) {
        val request = assertNotNull(constraints.requiredNetworkRequest)
        assertFalse(request.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET))
        assertFalse(request.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
        assertFalse(request.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN))
        assertTrue(request.hasCapability(NetworkCapabilities.NET_CAPABILITY_TRUSTED))
        assertTrue(request.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_RESTRICTED))
    }
}
