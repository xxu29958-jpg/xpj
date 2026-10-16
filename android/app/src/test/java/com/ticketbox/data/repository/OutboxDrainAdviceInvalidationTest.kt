package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

/** 218-B4 review: the drain engine's advice-input replay seam
 *  ([OutboxDrainEngine.onAdviceInputReplaySucceeded]) — kind classification
 *  and success-only firing. Split out of OutboxDrainEngineTest when the
 *  class crossed the LargeClass cap. */
class OutboxDrainAdviceInvalidationTest {
    @Test
    fun incomeCreationReplayInvalidatesAdviceAfterDoneWithoutAnIncomeScreen() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val engine = OutboxDrainEngine(outbox,
            listOf(TypedStubDispatcher(type = PendingMutationType.CreateIncomePlan)))
        val rowId = outbox.enqueue(PendingMutationType.CreateIncomePlan,
            "income_plan_create:original", "{}", 0L, "original")
        var fired = 0
        engine.onAdviceInputReplaySucceeded = {
            assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.getValue(rowId).status)
            fired += 1
        }

        dao.runnableBatches += listOf(dao.rows.keys.single())
        assertEquals(1, engine.drainOnce().done)
        assertEquals(1, fired)
    }

    @Test
    fun unacceptedIncomeCreationNeverPublishesAdviceInputSuccess() = runTest {
        val refusals = listOf(
            DispatchResult.RetryableFailure("offline"),
            DispatchResult.Failure("client_upgrade_required"),
            DispatchResult.Conflict("original requires review"),
            DispatchResult.Discarded("not an accepted creation"),
        )
        for (result in refusals) {
            val (engine, outbox, dao) = withDispatcher(TypedStubDispatcher(
                type = PendingMutationType.CreateIncomePlan, result = result))
            var fired = 0
            engine.onAdviceInputReplaySucceeded = { fired += 1 }
            outbox.enqueue(PendingMutationType.CreateIncomePlan,
                "income_plan_create:original", "{}", 0L, "original")

            dao.runnableBatches += listOf(dao.rows.keys.single())
            assertEquals(0, engine.drainOnce().done, result.toString())
            assertEquals(0, fired, result.toString())
        }
    }

    @Test
    fun adviceInputReplaySuccessFiresInvalidationSeam() = runTest {
        // 218-B4 review: advice generated between queue and replay used the
        // pre-replay server state — a successful replay of an advice-input
        // kind must invalidate it.
        val (engine, outbox, dao) = withDispatcher(
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

        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, fired)
    }

    @Test
    fun confirmedCorrectionReplaySuccessInvalidatesAdviceInputs() = runTest {
        val (engine, outbox, dao) = withDispatcher(
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

        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, fired)
    }

    @Test
    fun nonInputReplaySuccessDoesNotFireInvalidationSeam() = runTest {
        // Spending goals travel the outbox but are not an advisor input.
        val (engine, outbox, dao) = withDispatcher(
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

        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(0, fired)
    }

    @Test
    fun failedAdviceInputReplayDoesNotFireInvalidationSeam() = runTest {
        // Retry/failure leaves the server state unchanged — no invalidation.
        val (engine, outbox, dao) = withDispatcher(
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

        dao.runnableBatches += listOf(dao.rows.keys.single())
        engine.drainOnce()

        assertEquals(0, fired)
    }

    @Test
    fun savingABudgetLimitDoesNotDiscardAdviceFromUnchangedFinancialInputs() = runTest {
        // The advisor reads expense history, income and recurring commitments, not the saved limit.
        val (engine, outbox, dao) = withDispatcher(TypedStubDispatcher(type = PendingMutationType.SaveMonthlyBudget))
        var fired = 0
        engine.onAdviceInputReplaySucceeded = { fired += 1 }
        outbox.enqueue(PendingMutationType.SaveMonthlyBudget, "monthly_budget:2026-09", "{}", 1L, "budget-original")
        dao.runnableBatches += listOf(dao.rows.keys.single())
        assertEquals(1, engine.drainOnce().done)
        assertEquals(0, fired)
    }

    @Test
    fun replaceItemsReplaySuccessDoesNotFireInvalidationSeam() = runTest {
        // 218-B4 review P2-24 (verified): replace_expense_items rewrites
        // ExpenseItem sub-lines + updated_at + items_sum_status only; the
        // advisor reads the confirmed financial stream through spending_projection_service,
        // never line items — nothing it reads moves.
        val (engine, outbox, dao) = withDispatcher(
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

        dao.runnableBatches += listOf(dao.rows.keys.single())
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(0, fired)
    }

    private fun withDispatcher(
        dispatcher: OutboxMutationDispatcher,
    ): Triple<OutboxDrainEngine, OutboxRepository, FakePendingMutationDao> {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        return Triple(engine, outbox, dao)
    }
}

private class TypedStubDispatcher(
    private val result: DispatchResult? = null,
    override val type: PendingMutationType,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow): DispatchResult =
        result ?: DispatchResult.Success()
}
