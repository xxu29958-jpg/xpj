package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class OutboxSettlementAtomicityTest {

    @Test
    fun successSettlesDoneAndTokenCascadeInOneDaoTransactionBeforeReplayNotification() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val firstId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val secondId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val engine = OutboxDrainEngine(outbox, listOf(fixedDispatcher(PendingMutationType.PatchExpense, DispatchResult.Success(newRowVersion = 2L))))

        var siblingTokenAtPublication: Long? = null
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            outbox.acceptedReplayRevision.collect { revision ->
                if (revision > 0L) siblingTokenAtPublication = dao.rows.getValue(secondId).expectedRowVersion
            }
        }

        dao.tokenCascadeIds += listOf(secondId)
        dao.runnableBatches += listOf(firstId)
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, dao.doneAndCascadeCalls.size)
        val (doneUpdate, cascade) = dao.doneAndCascadeCalls.single()
        assertEquals(firstId, doneUpdate.id)
        assertEquals(PendingMutationStatus.Done.wireValue, doneUpdate.status)
        assertNotNull(cascade)
        assertEquals("expense:1", cascade.targetId)
        assertEquals(2L, cascade.freshToken)
        assertEquals(1, dao.tokenCascadeCalls.size)
        assertEquals(2L, dao.rows.getValue(secondId).expectedRowVersion)
        assertEquals(2L, siblingTokenAtPublication)
    }

    @Test
    fun cascadeFailureRollsBackDoneUpdateAtomically() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val firstId = outbox.enqueue(PendingMutationType.ReplaceSplits, "expense:1", "{}", 1L)
        val secondId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val engine = OutboxDrainEngine(outbox, listOf(fixedDispatcher(PendingMutationType.ReplaceSplits, DispatchResult.Success(newRowVersion = 2L))))

        dao.tokenCascadeError = SQLiteException("simulated cascade failure")
        dao.runnableBatches += listOf(firstId)

        assertFailsWith<SQLiteException> { engine.drainOnce() }
        assertEquals(PendingMutationStatus.InFlight.wireValue, dao.rows.getValue(firstId).status)
        assertNull(dao.rows.getValue(firstId).completedAt)
        assertEquals(1L, dao.rows.getValue(secondId).expectedRowVersion)
        assertEquals(0L, outbox.acceptedReplayRevision.value)

        val recurringDao = FakePendingMutationDao()
        val recurringOutbox = testOutboxRepository(recurringDao)
        val patchId = recurringOutbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 1L)
        val siblingId = recurringOutbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 1L)
        val patchEngine = OutboxDrainEngine(recurringOutbox, listOf(fixedDispatcher(PendingMutationType.PatchExpense, DispatchResult.Success(newRowVersion = 2L))))
        recurringDao.tokenCascadeError = SQLiteException("simulated cascade failure")
        recurringDao.runnableBatches += listOf(patchId)

        assertFailsWith<SQLiteException> { patchEngine.drainOnce() }
        assertEquals(PendingMutationStatus.Pending.wireValue, recurringDao.rows.getValue(patchId).status)
        assertEquals("accepted_recurring_read_publication_pending", recurringDao.rows.getValue(patchId).lastError)
        assertNull(recurringDao.rows.getValue(patchId).completedAt)
        assertEquals(1L, recurringDao.rows.getValue(siblingId).expectedRowVersion)
        assertEquals(0L, recurringOutbox.acceptedReplayRevision.value)
    }

    @Test
    fun createExpenseNeverCascadesTokenEvenWithPositiveRowVersion() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val createId = outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:abc", "{}", 0L)
        val followUpId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:local:abc", "{}", 0L)
        val engine = OutboxDrainEngine(outbox, listOf(fixedDispatcher(PendingMutationType.CreateExpense, DispatchResult.Success(newRowVersion = 5L))))

        dao.runnableBatches += listOf(createId)
        val summary = engine.drainOnce()

        assertEquals(1, summary.done)
        assertEquals(1, dao.doneAndCascadeCalls.size)
        assertNull(dao.doneAndCascadeCalls.single().second)
        assertTrue(dao.tokenCascadeCalls.isEmpty())
        assertEquals(0L, dao.rows.getValue(followUpId).expectedRowVersion)
    }

    @Test
    fun nonPositiveOrNullRowVersionNeverCascadesToken() = runTest {
        for (version in listOf<Long?>(null, 0L, -1L)) {
            val dao = FakePendingMutationDao()
            val outbox = testOutboxRepository(dao)
            val firstId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 3L)
            val secondId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 3L)
            val engine = OutboxDrainEngine(outbox, listOf(fixedDispatcher(PendingMutationType.PatchExpense, DispatchResult.Success(newRowVersion = version))))

            dao.runnableBatches += listOf(firstId)
            assertEquals(1, engine.drainOnce().done)
            assertEquals(1, dao.doneAndCascadeCalls.size)
            assertNull(dao.doneAndCascadeCalls.single().second, "version=$version must not cascade")
            assertTrue(dao.tokenCascadeCalls.isEmpty(), "version=$version must not call cascadeFreshTokenForTarget")
            assertEquals(3L, dao.rows.getValue(secondId).expectedRowVersion)
        }
    }

    @Test
    fun internalSettlementScopesCascadeToAcceptedRowWithoutReadingCurrentBinding() = runTest {
        val originalBinding = testOutboxBinding(ledgerId = "ledger-a")
        var currentBinding = originalBinding
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao, bindingProvider = { currentBinding })
        val firstId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:9", "{}", 1L)
        val secondId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:9", "{}", 1L)
        val firstRow = dao.rows.getValue(firstId).toDomain()

        currentBinding = testOutboxBinding(ledgerId = "ledger-b")

        assertTrue(outbox.markDone(firstId, OutboxDoneSettlement(acceptedRow = firstRow, cascadeNewToken = 0L)))
        assertTrue(dao.tokenCascadeCalls.isEmpty())

        dao.tokenCascadeIds += listOf(secondId)
        assertTrue(outbox.markDone(firstId, OutboxDoneSettlement(acceptedRow = firstRow, cascadeNewToken = 4L)))
        val call = dao.tokenCascadeCalls.single()
        assertEquals(originalBinding.ownerStorageKey, call.ownerKey)
        assertEquals("ledger-a", call.ledgerId)
        assertEquals("expense:9", call.targetId)
        assertEquals(4L, call.freshToken)
        assertEquals(4L, dao.rows.getValue(secondId).expectedRowVersion)
    }

    @Test
    fun missingRowAtSettlementSkipsCascadeNotificationAndDoneCount() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val firstId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val siblingId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        var adviceInvalidations = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dao.rows.remove(row.id)
                return DispatchResult.Success(newRowVersion = 2L)
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher)).apply {
            onAdviceInputReplaySucceeded = { adviceInvalidations++ }
        }

        dao.tokenCascadeIds += listOf(siblingId)
        dao.runnableBatches += listOf(firstId)
        val summary = engine.drainOnce()

        assertEquals(1, summary.attempted)
        assertEquals(0, summary.done)
        assertFalse(summary.anythingChanged)
        assertEquals(0L, outbox.acceptedReplayRevision.value)
        assertEquals(0, adviceInvalidations)
        assertTrue(dao.tokenCascadeCalls.isEmpty())
        assertEquals(1L, dao.rows.getValue(siblingId).expectedRowVersion)
        assertFalse(outbox.markDone(firstId))
    }

    @Test
    fun partialPrepareReadProtectionFailureRollsBackAlreadyPreparedHooksAsUnsent() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val recurringResults = mutableListOf<DispatchResult?>()
        val debtResults = mutableListOf<DispatchResult?>()
        outbox.onRecurringDispatchPreparing = {}
        outbox.onRecurringDispatchFinished = { _, result -> recurringResults += result }
        outbox.onDebtDispatchPreparing = { throw SQLiteException("debt barrier write failed") }
        outbox.onDebtDispatchFinished = { _, result -> debtResults += result }

        val rowId = outbox.enqueue(PendingMutationType.ConfirmRepaymentDraft, "repayment_draft:1", "{}", 1L, "k-prep")
        dao.runnableBatches += listOf(rowId)
        val dispatcher = fixedDispatcher(PendingMutationType.ConfirmRepaymentDraft, DispatchResult.Success(newRowVersion = 2L))

        assertFailsWith<SQLiteException> { OutboxDrainEngine(outbox, listOf(dispatcher)).drainOnce() }
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.getValue(rowId).status)
        assertEquals(0, dao.rows.getValue(rowId).retryCount)
        assertTrue(recurringResults.first() is DispatchResult.Failure)
        assertTrue((recurringResults.first() as DispatchResult.Failure).definitelyRejected)
        assertEquals(listOf<DispatchResult?>(null), debtResults)
    }

    private fun fixedDispatcher(
        type: PendingMutationType,
        result: DispatchResult,
    ): OutboxMutationDispatcher = object : OutboxMutationDispatcher {
        override val type = type
        override suspend fun dispatch(row: OutboxRow): DispatchResult = result
    }
}
