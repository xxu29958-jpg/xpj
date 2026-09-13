package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** The real drain engine publishes acceptance after its DAO settlement, independently of UI callbacks. */
@OptIn(ExperimentalCoroutinesApi::class)
class OutboxAcceptedReplayTest {
    @Test fun acceptanceFollowsDoneAndReceiptAndRemainsVisibleToLateCollectors() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val id = enqueue(outbox, "original")
        val original = dao.rows.getValue(id)
        val probe = ReplayAcceptanceProbe()
        val engine = OutboxDrainEngine(outbox, listOf(probe))
        val observed = mutableListOf<Long>()
        var rowAtPublication: PendingMutationEntity? = null
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            outbox.acceptedReplayRevision.collect { revision ->
                observed += revision
                // This observer runs immediately at publication, before the engine can continue.
                if (revision > 0L) rowAtPublication = dao.rows.getValue(id)
            }
        }

        assertEquals(1, engine.drainOnce().done)

        assertEquals(listOf(0L, 1L), observed)
        val published = assertNotNull(rowAtPublication)
        assertEquals(PendingMutationStatus.Done.wireValue, published.status)
        assertEquals(ACCEPTED_RECEIPT, published.receiptJson)
        assertEquals(original.payload, published.payload)
        assertEquals(original.idempotencyKey, published.idempotencyKey)
        assertEquals(original.expectedRowVersion, published.expectedRowVersion)
        assertEquals(original.ownerKey, published.ownerKey)
        assertEquals(original.ledgerId, published.ledgerId)
        assertEquals(1L, outbox.acceptedReplayRevision.first())
        assertEquals(0, engine.drainOnce().attempted)
        assertEquals(listOf(0L, 1L), observed)
        assertEquals(1, probe.calls.size)
    }

    @Test fun discardedConflictRetryableAndFailedRowsNeverPublishAcceptance() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val outcomes = listOf(
            DispatchResult.Discarded("target no longer exists") to PendingMutationStatus.Done,
            DispatchResult.Conflict("original requires review") to PendingMutationStatus.Conflict,
            DispatchResult.RetryableFailure("offline") to PendingMutationStatus.Pending,
            DispatchResult.Failure("client_upgrade_required") to PendingMutationStatus.Failed,
        ).mapIndexed { index, outcome -> enqueue(outbox, "refusal-$index") to outcome }.toMap()
        val probe = ReplayAcceptanceProbe { row -> outcomes.getValue(row.id).first }

        val summary = OutboxDrainEngine(outbox, listOf(probe)).drainOnce()

        assertEquals(4, summary.attempted)
        assertEquals(0, summary.done)
        assertEquals(1, summary.discarded)
        assertEquals(1, summary.conflicts)
        assertEquals(1, summary.retryable)
        assertEquals(1, summary.failures)
        assertEquals(outcomes.keys, probe.calls.toSet())
        for ((id, outcome) in outcomes) {
            assertEquals(outcome.second.wireValue, dao.rows.getValue(id).status)
            assertEquals(null, dao.rows.getValue(id).receiptJson)
        }
        assertEquals(0L, outbox.acceptedReplayRevision.first())
    }

    @Test fun mismatchedBindingDoesNotSendAndReturningToTheOriginalBindingPublishesAcceptance() = runTest {
        val originalBinding = testOutboxBinding()
        var binding = originalBinding
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao, bindingProvider = { binding })
        val id = enqueue(outbox, "bound-original")
        val original = dao.rows.getValue(id)
        val probe = ReplayAcceptanceProbe()
        val engine = OutboxDrainEngine(outbox, listOf(probe))

        outbox.withBindingTransition { binding = originalBinding.copy(ledgerId = "another-ledger") }
        assertEquals(0, engine.drainOnce().attempted)
        assertTrue(probe.calls.isEmpty())
        assertEquals(0L, outbox.acceptedReplayRevision.value)
        assertEquals(original, dao.rows.getValue(id))

        outbox.withBindingTransition { binding = originalBinding }
        assertEquals(0L, outbox.acceptedReplayRevision.value)
        assertEquals(1, engine.drainOnce().done)
        assertEquals(listOf(id), probe.calls)
        assertEquals(1L, outbox.acceptedReplayRevision.first())
        assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.getValue(id).status)
        assertEquals(ACCEPTED_RECEIPT, dao.rows.getValue(id).receiptJson)
    }

    private suspend fun enqueue(outbox: OutboxRepository, target: String) = outbox.enqueue(
        PendingMutationType.SaveMonthlyBudget, target, "{\"original\":\"$target\"}", 3L, "key-$target")
}

private const val ACCEPTED_RECEIPT = "{\"accepted\":\"original-receipt\"}"

private class ReplayAcceptanceProbe(
    private val outcome: (OutboxRow) -> DispatchResult = { DispatchResult.Success(receiptJson = ACCEPTED_RECEIPT) },
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.SaveMonthlyBudget
    val calls = mutableListOf<Long>()

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        calls += row.id
        return outcome(row)
    }
}
