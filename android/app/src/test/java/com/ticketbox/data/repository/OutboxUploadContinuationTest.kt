package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class OutboxUploadContinuationTest {
    @Test
    fun capacityStopsTheOriginalTailAndExplicitRetryContinuesWithoutResendingA() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val ids = enqueue(outbox, 3)
        val sends = mutableListOf<Long>()
        var full = true
        val engine = engine(outbox) { row ->
            sends += row.id
            if (row.id == ids[1] && full) DispatchResult.Failure(UPLOAD_CAPACITY_FULL)
            else DispatchResult.Success(receiptJson = "original-${row.id}")
        }
        val first = engine.drainOnce()
        assertEquals(listOf(ids[0], ids[1]), sends)
        assertEquals(1, first.done)
        assertEquals(1, first.failures)
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.getValue(ids[2]).status)
        val original = dao.rows.getValue(ids[1])
        full = false
        assertTrue(outbox.resolveFailed(ids[1], FailedResolution.Retry()))
        assertEquals(2, engine.drainOnce().done)
        assertEquals(listOf(ids[0], ids[1], ids[1], ids[2]), sends)
        assertEquals(original.payload, dao.rows.getValue(ids[1]).payload)
        assertEquals(original.idempotencyKey, dao.rows.getValue(ids[1]).idempotencyKey)
    }

    @Test
    fun ordinaryFailureRetainsBAndDeliversCInTheSameBoundedDrain() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val ids = enqueue(outbox, 3)
        val sends = mutableListOf<Long>()
        val summary = engine(outbox) { row ->
            sends += row.id
            if (row.id == ids[1]) DispatchResult.Failure("unreadable", blocksFollowing = false)
            else DispatchResult.Success()
        }.drainOnce()
        assertEquals(ids, sends)
        assertEquals(2, summary.done)
        val retained = dao.rows.getValue(ids[1])
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertFalse(retained.blocksFollowing)
        assertEquals("original-1", retained.payload)
    }

    @Test
    fun aTransientHeadIsAttemptedOnlyOnceAndDoesNotStarveAnotherTarget() = runTest {
        val outbox = testOutboxRepository(FakePendingMutationDao())
        val ids = enqueue(outbox, 3)
        val other = outbox.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:other", "other", 0L, "other-key")
        val sends = mutableListOf<Long>()
        val summary = engine(outbox) { row ->
            sends += row.id
            if (row.id == ids[0]) DispatchResult.RetryableFailure("in progress") else DispatchResult.Success()
        }.drainOnce()
        assertEquals(listOf(ids[0], other), sends)
        assertEquals(1, summary.retryable)
        assertEquals(1, summary.done)
        assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.classify(summary))
    }

    @Test
    fun boundedDrainLeavesExplicitContinuationForTheOriginalWorker() = runTest {
        val outbox = testOutboxRepository(FakePendingMutationDao())
        val ids = enqueue(outbox, 101)
        val sends = mutableListOf<Long>()
        val engine = engine(outbox) { row -> sends += row.id; DispatchResult.Success() }
        val first = engine.drainOnce()
        assertEquals(ids.take(100), sends)
        assertTrue(first.continuationRequired)
        assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.classify(first))
        assertEquals(1, engine.drainOnce().done)
        assertEquals(ids, sends)
    }

    @Test
    fun staleTailClaimKeepsAWorkerContinuationAfterTheRetriedPredecessorSettles() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val ids = enqueue(outbox, 2)
        outbox.markFailed(ids[0], "ordinary_upload_failure", blocksFollowing = false)
        val originalTail = dao.rows.getValue(ids[1])
        dao.beforeNextRunnableBatchReturn = {
            dao.beforeNextRunnableBatchReturn = null
            assertTrue(outbox.resolveFailed(ids[0], FailedResolution.Retry()))
        }
        val sends = mutableListOf<Long>()
        val engine = engine(outbox) { row -> sends += row.id; DispatchResult.Success() }

        val first = engine.drainOnce()
        assertEquals(listOf(ids[0]), sends)
        assertEquals(1, first.done)
        assertEquals(1, first.raced)
        val retainedTail = dao.rows.getValue(ids[1])
        assertEquals(originalTail, retainedTail)
        assertTrue(first.continuationRequired)
        assertEquals(OutboxDrainWorker.DrainOutcome.RETRY, OutboxDrainWorker.classify(first))

        assertEquals(1, engine.drainOnce().done)
        assertEquals(ids, sends)
        assertEquals(originalTail.payload, dao.rows.getValue(ids[1]).payload)
        assertEquals(originalTail.idempotencyKey, dao.rows.getValue(ids[1]).idempotencyKey)
    }

    private suspend fun enqueue(outbox: OutboxRepository, count: Int) = (0 until count).map { index ->
        outbox.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:original", "original-$index", 0L, "key-$index")
    }

    private fun engine(outbox: OutboxRepository, send: suspend (OutboxRow) -> DispatchResult) = OutboxDrainEngine(outbox,
        listOf(object : OutboxMutationDispatcher {
            override val type = PendingMutationType.UploadScreenshot
            override suspend fun dispatch(row: OutboxRow) = send(row)
        }))
}
