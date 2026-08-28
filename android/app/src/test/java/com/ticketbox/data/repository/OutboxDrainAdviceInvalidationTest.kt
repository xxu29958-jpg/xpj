package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

/** 218-B4 review: the drain engine's advice-input replay seam
 *  ([OutboxDrainEngine.onAdviceInputReplaySucceeded]) — kind classification
 *  and success-only firing. Split out of OutboxDrainEngineTest when the
 *  class crossed the LargeClass cap. */
class OutboxDrainAdviceInvalidationTest {
    @Test
    fun adviceInputReplaySuccessFiresInvalidationSeam() = runTest {
        // 218-B4 review: advice generated between queue and replay used the
        // pre-replay server state — a successful replay of an advice-input
        // kind must invalidate it.
        val (engine, outbox) = withDispatcher(
            TypedStubDispatcher(type = PendingMutationType.UpdateIncomePlan),
        )
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(
            type = PendingMutationType.UpdateIncomePlan,
            targetId = "income-plan:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, fired)
    }

    @Test
    fun confirmedCorrectionReplaySuccessInvalidatesAdviceInputs() = runTest {
        val (engine, outbox) = withDispatcher(
            TypedStubDispatcher(type = PendingMutationType.CorrectExpense),
        )
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(
            type = PendingMutationType.CorrectExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 2L,
            idempotencyKey = "correction-intent",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, fired)
    }

    @Test
    fun nonInputReplaySuccessDoesNotFireInvalidationSeam() = runTest {
        // Spending goals travel the outbox but are not an advisor input
        // (nor is the monthly-budget row — it never travels the outbox).
        val (engine, outbox) = withDispatcher(
            TypedStubDispatcher(type = PendingMutationType.UpdateGoal),
        )
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(
            type = PendingMutationType.UpdateGoal,
            targetId = "goal:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(0, fired)
    }

    @Test
    fun failedAdviceInputReplayDoesNotFireInvalidationSeam() = runTest {
        // Retry/failure leaves the server state unchanged — no invalidation.
        val (engine, outbox) = withDispatcher(
            TypedStubDispatcher(
                result = DispatchResult.RetryableFailure("offline again"),
                type = PendingMutationType.ConfirmExpense,
            ),
        )
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(
            type = PendingMutationType.ConfirmExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        engine.drainOnce()

        assertEquals(0, fired)
    }

    @Test
    fun replaceItemsReplaySuccessDoesNotFireInvalidationSeam() = runTest {
        // 218-B4 review P2-24 (verified): replace_expense_items rewrites
        // ExpenseItem sub-lines + updated_at + items_sum_status only; the
        // advisor aggregates Expense.category / amount_cents / month via
        // confirmed_amount_query, never line items — nothing it reads moves.
        val (engine, outbox) = withDispatcher(
            TypedStubDispatcher(type = PendingMutationType.ReplaceItems),
        )
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(
            type = PendingMutationType.ReplaceItems,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(0, fired)
    }

    private fun withDispatcher(
        dispatcher: OutboxMutationDispatcher,
    ): Pair<OutboxDrainEngine, OutboxRepository> {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        return engine to outbox
    }
}

private class TypedStubDispatcher(
    private val result: DispatchResult? = null,
    override val type: PendingMutationType,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow): DispatchResult =
        result ?: DispatchResult.Success()
}
