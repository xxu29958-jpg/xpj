package com.ticketbox.data.repository

import com.ticketbox.data.repository.OutboxDrainWorker.DrainOutcome
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * Unit tests for the post-drain classification — the only piece of
 * [OutboxDrainWorker] that has interesting logic. We don't exercise
 * the Android-bound ``doWork`` directly: that branch is a one-liner
 * over [classify] plus the [TicketboxApplication.container] lookup,
 * and bringing Robolectric in just for that lookup would dwarf the
 * test surface.
 */
class OutboxDrainWorkerTest {

    private fun summary(
        attempted: Int = 0,
        done: Int = 0,
        conflicts: Int = 0,
        failures: Int = 0,
        retryable: Int = 0,
        discarded: Int = 0,
        unsupported: Int = 0,
        raced: Int = 0,
    ) = DrainSummary(
        attempted = attempted,
        done = done,
        conflicts = conflicts,
        failures = failures,
        retryable = retryable,
        discarded = discarded,
        unsupported = unsupported,
        raced = raced,
    )

    @Test
    fun `idle queue → SUCCESS`() {
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 0)),
        )
    }

    @Test
    fun `all retryable → RETRY (backoff)`() {
        // Pure network-blip batch: every row came back transient. We
        // want WorkManager to back off rather than re-fire on the
        // current schedule and burn cycles on the same dead network.
        assertEquals(
            DrainOutcome.RETRY,
            OutboxDrainWorker.classify(summary(attempted = 3, retryable = 3)),
        )
    }

    @Test
    fun `mixed retryable plus done → SUCCESS`() {
        // At least one row moved forward. SUCCESS lets the next
        // periodic tick start fresh on the existing schedule rather
        // than waiting out a backoff window.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(
                summary(attempted = 4, done = 1, retryable = 3),
            ),
        )
    }

    @Test
    fun `conflict only → SUCCESS (user has to resolve)`() {
        // Conflicts are user-resolvable surface state, not a worker
        // failure — flag SUCCESS so the schedule continues normally.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 2, conflicts = 2)),
        )
    }

    @Test
    fun `failure only → SUCCESS (user has to resolve)`() {
        // Same logic as conflict: a permanent FAILED row is the
        // user's problem to fix, not the worker's reason to retry.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 1, failures = 1)),
        )
    }

    @Test
    fun `discarded only → SUCCESS`() {
        // Server told us the row is moot (404 / structural 409).
        // No backoff needed.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 1, discarded = 1)),
        )
    }

    @Test
    fun `unsupported only → SUCCESS`() {
        // No dispatcher registered yet for this row's type. Engine
        // already marked the row FAILED with
        // ``no_dispatcher_registered:<wire>``; the user can drop or
        // retry-after-upgrade. The worker has nothing to retry.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 1, unsupported = 1)),
        )
    }

    @Test
    fun `all raced → SUCCESS`() {
        // Another concurrent drain (a one-time worker firing on top
        // of a periodic, or a user-triggered drain) already claimed
        // every row. We didn't do work but we didn't fail either —
        // the winning drain is the one taking responsibility.
        assertEquals(
            DrainOutcome.SUCCESS,
            OutboxDrainWorker.classify(summary(attempted = 3, raced = 3)),
        )
    }

    @Test
    fun `runDrain wraps engine fault as RETRY`() = runTest {
        // A non-cancellation Exception from drainOnce — e.g. DB
        // corruption, JVM OOM bubbled up by the engine — is mapped
        // to RETRY so WorkManager backs off and tries again rather
        // than terminating the drain permanently.
        val outcome = OutboxDrainWorker.runDrain {
            throw RuntimeException("DB lost")
        }
        assertEquals(DrainOutcome.RETRY, outcome)
    }

    @Test
    fun `runDrain rethrows CancellationException`() = runTest {
        // CancellationException must NOT be swallowed: the drain
        // engine itself rolls in-flight rows back to PENDING inside
        // a NonCancellable scope (round-2 P1#2); we just need to
        // let the cancellation propagate so WorkManager doesn't
        // count it as a backoff cycle.
        assertFailsWith<CancellationException> {
            OutboxDrainWorker.runDrain {
                throw CancellationException("test")
            }
        }
    }

    @Test
    fun `runDrain hands real summary to classify`() = runTest {
        // Sanity: a real engine return path lands at the same
        // outcome we'd get from calling classify() directly.
        val doneOutcome = OutboxDrainWorker.runDrain {
            summary(attempted = 2, done = 2)
        }
        assertEquals(DrainOutcome.SUCCESS, doneOutcome)

        val retryOutcome = OutboxDrainWorker.runDrain {
            summary(attempted = 1, retryable = 1)
        }
        assertEquals(DrainOutcome.RETRY, retryOutcome)
    }
}
