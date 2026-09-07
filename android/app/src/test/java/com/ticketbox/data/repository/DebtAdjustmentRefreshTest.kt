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
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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
        val outbox = OutboxRepository(onRowsDeleted = {}, dao = delayed, clock = fixture.clock,
            bindingProvider = { fixture.provider.currentSession().toOutboxBinding() }, onEnqueued = {})
        val events = mutableListOf<DebtAdjustmentObservation>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.newRepository(outbox).observeAdjustments().collect { events += it }
        }
        runCurrent()
        assertTrue(events.isEmpty(), "No synthetic empty snapshot may release the initial read")

        ready.complete(Unit)
        runCurrent()

        assertEquals(fixture.binding, events.single().binding)
        assertTrue(events.single().initial)
        assertTrue(events.single().newlyTerminal.isEmpty())
        assertEquals(PendingMutationStatus.Done, events.single().adjustments.single().row.status)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun newDoneRefreshesOnceAndRetentionDoesNotReplayOrHideTheNextCompletion() = runTest {
        val fixture = DebtAdjustmentFixture()
        val historicalId = fixture.save().getOrThrow()
        fixture.outbox.markDone(historicalId)
        val events = mutableListOf<DebtAdjustmentObservation>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeAdjustments().collect { events += it }
        }
        runCurrent()
        val next = fixture.save().getOrThrow()
        fixture.outbox.markFailed(next, "debt_adjustment_response_unverified")
        runCurrent()
        assertEquals(1, events.count { it.requiresRefresh }, "Pending and Failed are not confirmed completion")
        assertEquals(setOf("debt:${fixture.debt.publicId}"), events.last().unresolvedTargetIds)
        fixture.outbox.markDone(next)
        runCurrent()
        fixture.outbox.markDone(next)
        runCurrent()
        assertEquals(listOf(true, false), events.filter { it.requiresRefresh }.map { it.initial })

        val later = fixture.newOutbox(Clock.offset(fixture.clock, Duration.ofDays(2)))
        assertEquals(2, later.gcCompleted(retentionMillis = Duration.ofDays(1).toMillis()))
        runCurrent()
        assertEquals(2, events.count { it.requiresRefresh }, "Removing retained Done rows is not a new completion")
        val following = fixture.save().getOrThrow()
        runCurrent()
        assertEquals(2, events.count { it.requiresRefresh })
        fixture.outbox.markDone(following)
        runCurrent()

        assertEquals(listOf(true, false, false), events.filter { it.requiresRefresh }.map { it.initial })
        assertTrue(events.all { it.binding == fixture.binding })
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(following).status)
    }

    @Test
    fun bindingReplacementAndCollectorReopenRequireTheirOwnAuthoritativeInitialRead() = runTest {
        val fixture = DebtAdjustmentFixture()
        fixture.outbox.markDone(fixture.save().getOrThrow())
        val events = mutableListOf<DebtAdjustmentObservation>()
        val observer = backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeAdjustments().collect { events += it }
        }
        runCurrent()
        fixture.session.switchLedgerForFixture("other", "另一账本")
        runCurrent()
        val replacement = requireNotNull(fixture.repository.currentAccess()).binding
        assertEquals(listOf(fixture.binding, replacement), events.map { it.binding })
        assertTrue(events.all { it.initial })
        observer.cancel()

        val reopened = mutableListOf<DebtAdjustmentObservation>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeAdjustments().collect { reopened += it }
        }
        runCurrent()
        assertEquals(listOf(DebtAdjustmentObservation(replacement, emptyList(), true, emptyList())), reopened)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun localStopNotifiesContinuationButReopenNeverClaimsDeliveryOrReplays() = runTest {
        val fixture = DebtAdjustmentFixture()
        val events = mutableListOf<DebtAdjustmentObservation>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            fixture.repository.observeAdjustments().collect { events += it }
        }
        val id = fixture.save().getOrThrow()
        fixture.outbox.markFailed(id, "debt_adjustment_response_unverified")
        runCurrent()
        val original = fixture.dao.rows.getValue(id)
        fixture.repository.recover(fixture.binding, fixture.pending(), true).getOrThrow()
        runCurrent()
        val stopped = fixture.dao.rows.getValue(id)
        assertEquals(original.copy(status = "abandoned", completedAt = stopped.completedAt), stopped)
        assertTrue(stopped.completedAt != null)
        assertEquals(listOf(id), events.last().newlyTerminal.map { it.row.id })
        assertTrue(events.last().unresolvedTargetIds.isEmpty())
        val reopened = fixture.newRepository(fixture.outbox).observeAdjustments().first()
        assertTrue(reopened.initial)
        assertTrue(reopened.newlyTerminal.isEmpty())
        assertEquals(PendingMutationStatus.Abandoned, reopened.adjustments.single().row.status)
        assertTrue(reopened.acceptsCanonical(fixture.debt), "A post-stop read may retain the original RV")
        val later = fixture.newOutbox(Clock.offset(fixture.clock, Duration.ofDays(40)))
        assertEquals(0, later.gcCompleted(retentionMillis = 0))
        assertEquals(0, later.reapExpiredPending(fixture.clock.millis() + Duration.ofDays(40).toMillis()))
        assertTrue(fixture.outbox.activeForTarget("debt:${fixture.debt.publicId}").isEmpty())
        assertEquals(0, fixture.engine().drainOnce().attempted)
        assertEquals(listOf(1, 1), fixture.queueDepthAtSchedule)
        assertTrue(fixture.api.calls.isEmpty())
    }

    @Test
    fun stopCasRefusesRetriedInFlightDoneAndForeignBindingRows() = runTest {
        val fixture = DebtAdjustmentFixture()
        val id = fixture.save().getOrThrow()
        fixture.outbox.markFailed(id, "debt_adjustment_response_unverified")
        val original = fixture.pending()
        val bound = LedgerRequestGuard(fixture.provider).bindExact(fixture.binding)
        fixture.repository.recover(fixture.binding, original, false).getOrThrow()
        assertFalse(fixture.outbox.abandonDebtAdjustment(bound, original.row))
        for (status in listOf("pending", "in_flight", "done")) {
            val current = fixture.dao.rows.getValue(id).copy(status = status)
            fixture.dao.rows[id] = current
            assertEquals(0, fixture.dao.abandonDebtAdjustment(id, requireNotNull(current.ownerKey), current.ledgerId, status, "stop"))
            assertEquals(current, fixture.dao.rows.getValue(id))
        }
        val failed = fixture.dao.rows.getValue(id).copy(status = "failed")
        fixture.dao.rows[id] = failed
        assertEquals(0, fixture.dao.abandonDebtAdjustment(id, "other-owner", failed.ledgerId, "failed", "stop"))
        assertEquals(0, fixture.dao.abandonDebtAdjustment(id, requireNotNull(failed.ownerKey), "other-ledger", "failed", "stop"))
        assertEquals(failed, fixture.dao.rows.getValue(id))
    }
}
