package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import java.time.Clock
import java.time.Duration
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtAdjustmentRefreshTest {
    @Test
    fun firstRefreshWaitsForActualSnapshotAndHistoricalDoneOnlyInitializesTheRead() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.outbox.markDone(fixture.save().getOrThrow())
        val ready = CompletableDeferred<Unit>()
        val delayed = object : PendingMutationDao by fixture.dao {
            override fun observeActiveByTypes(ownerKey: String, ledgerId: String,
                types: Collection<String>, activeStatuses: Collection<String>): Flow<List<PendingMutationEntity>> = flow {
                ready.await()
                emitAll(fixture.dao.observeActiveByTypes(ownerKey, ledgerId, types, activeStatuses))
            }
        }
        val outbox = OutboxRepository(delayed, fixture.clock,
            bindingProvider = { fixture.provider.currentSession().toOutboxBinding() }, onEnqueued = {})
        val events = mutableListOf<DebtAdjustmentRefresh>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.newRepository(outbox).observeCompletionRefreshes().collect { events += it }
        }
        runCurrent()
        assertTrue(events.isEmpty(), "No synthetic empty snapshot may release the initial read")

        ready.complete(Unit)
        runCurrent()

        assertEquals(listOf(DebtAdjustmentRefresh(fixture.binding, initial = true)), events)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun newDoneRefreshesOnceAndRetentionDoesNotReplayOrHideTheNextCompletion() = runTest {
        val fixture = DebtAdjustmentFixture()
        val historicalId = fixture.save().getOrThrow()
        fixture.outbox.markDone(historicalId)
        val events = mutableListOf<DebtAdjustmentRefresh>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeCompletionRefreshes().collect { events += it }
        }
        runCurrent()
        val next = fixture.save().getOrThrow()
        fixture.outbox.markFailed(next, "debt_adjustment_response_unverified")
        runCurrent()
        assertEquals(1, events.size, "Pending and Failed are not confirmed completion")
        fixture.outbox.markDone(next)
        runCurrent()
        fixture.outbox.markDone(next)
        runCurrent()
        assertEquals(listOf(true, false), events.map { it.initial })

        val later = fixture.newOutbox(Clock.offset(fixture.clock, Duration.ofDays(2)))
        assertEquals(2, later.gcCompleted(retentionMillis = Duration.ofDays(1).toMillis()))
        runCurrent()
        assertEquals(2, events.size, "Removing retained Done rows is not a new completion")
        val following = fixture.save().getOrThrow()
        runCurrent()
        assertEquals(2, events.size)
        fixture.outbox.markDone(following)
        runCurrent()

        assertEquals(listOf(true, false, false), events.map { it.initial })
        assertTrue(events.all { it.binding == fixture.binding })
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(following).status)
    }

    @Test
    fun bindingReplacementAndCollectorReopenRequireTheirOwnAuthoritativeInitialRead() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.outbox.markDone(fixture.save().getOrThrow())
        val events = mutableListOf<DebtAdjustmentRefresh>()
        val observer = backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeCompletionRefreshes().collect { events += it }
        }
        runCurrent()
        fixture.session.switchLedgerForFixture("other", "另一账本")
        runCurrent()
        val replacement = requireNotNull(fixture.repository.currentAccess()).binding
        assertEquals(listOf(fixture.binding, replacement), events.map { it.binding })
        assertTrue(events.all { it.initial })
        observer.cancel()

        val reopened = mutableListOf<DebtAdjustmentRefresh>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeCompletionRefreshes().collect { reopened += it }
        }
        runCurrent()
        assertEquals(listOf(DebtAdjustmentRefresh(replacement, initial = true)), reopened)
        assertTrue(fixture.api.calls.isEmpty())
    }
}
