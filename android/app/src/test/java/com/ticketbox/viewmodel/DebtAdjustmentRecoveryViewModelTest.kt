package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.DebtAdjustmentFixture
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.DebtKinds
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtAdjustmentRecoveryViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun preStopReadCannotReleaseBarrierAndConfirmedMissingTargetRetiresTheOldWriter() = runTest(dispatcher) {
        val adjustments = DebtAdjustmentFixture()
        val canonical = adjustments.debt
        val fresh = canonical.copy(rowVersion = 3L, remainingAmountCents = 53_000L)
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(canonical) }
        val model = DebtDetailViewModel(repo, adjustments.repository)
        val oldRead = CompletableDeferred<Unit>()
        val newRead = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            val id = adjustments.save().getOrThrow()
            adjustments.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            repo.getGate = oldRead
            model.refresh()
            runCurrent()
            repo.getResult = Result.success(fresh)
            repo.getGate = newRead
            adjustments.repository.recover(adjustments.binding, adjustments.pending(), true).getOrThrow()
            runCurrent()
            assertEquals(3, repo.getCalls.size)
            oldRead.complete(Unit)
            runCurrent()
            assertFalse(model.state.value.canWriteActions)
            assertEquals(canonical, model.state.value.debt)
            newRead.complete(Unit)
            advanceUntilIdle()
            assertEquals(fresh, model.state.value.debt)
            assertTrue(model.state.value.canWriteActions)

            repo.getGate = null
            repo.getResult = Result.failure(RepositoryException("这笔欠款不存在。", "debt_not_found"))
            model.refresh()
            advanceUntilIdle()
            assertNull(model.state.value.debt)
            assertFalse(model.state.value.canWriteActions)
            assertTrue(model.state.value.error != null)
            assertTrue(repo.mutations.isEmpty())
            assertEquals("abandoned", adjustments.dao.rows.getValue(id).status)
        } finally {
            oldRead.complete(Unit)
            newRead.complete(Unit)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun droppingUnverifiedAdjustmentBlocksOldFoldUntilCanonicalReadRecovers() = runTest(dispatcher) {
        val adjustments = DebtAdjustmentFixture()
        val canonical = adjustments.debt
        val fresh = canonical.copy(rowVersion = 3L, remainingAmountCents = 53_000L)
        val repo = AdjustmentDetailActions().apply {
            getResult = Result.success(canonical)
            writeResult = Result.success(fresh.copy(rowVersion = 4L, remainingAmountCents = 52_900L))
        }
        val model = DebtDetailViewModel(repo, adjustments.repository)
        val gate = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            model.openAction(DebtAction.Repayment)
            model.updateActionInput(amount = "1.00")
            val id = adjustments.save().getOrThrow()
            adjustments.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            assertFalse(model.state.value.canWriteActions)
            val original = adjustments.pending()
            repo.getResult = Result.failure(IllegalStateException("Synthetic unavailable canonical read"))
            repo.getGate = gate

            val priorJobs = model.viewModelScope.coroutineContext.job.children.toSet()
            model.recoverAdjustment(original, drop = true)
            model.viewModelScope.coroutineContext.job.children.single { it !in priorJobs }.join()
            runCurrent()
            assertTrue(adjustments.outbox.observeStatus().first().failed.none { it.id == id })
            assertTrue(adjustments.outbox.dequeueNextRunnable().isEmpty())
            assertEquals(listOf(canonical.publicId, canonical.publicId), repo.getCalls)
            assertFalse(model.state.value.canWriteActions)
            model.submit()
            model.selectKind(DebtKinds.REVOLVING)
            runCurrent()
            assertTrue(repo.mutations.isEmpty(), "Repayment and kind writes must remain blocked")
            assertEquals(canonical, model.state.value.debt)
            assertEquals("1.00", model.state.value.amountInput)
            gate.complete(Unit)
            advanceUntilIdle()
            assertFalse(model.state.value.canWriteActions)
            assertTrue(model.state.value.error != null)
            assertTrue(model.state.value.adjustmentWriteMessage != null)
            assertNull(model.state.value.flashMessage)

            repo.getGate = null
            repo.getResult = Result.success(fresh)
            model.refresh()
            advanceUntilIdle()
            assertEquals(fresh, model.state.value.debt)
            assertTrue(model.state.value.canWriteActions)
            assertNull(model.state.value.error)
            model.submit()
            advanceUntilIdle()
            assertEquals(listOf("repayment:${canonical.publicId}:3:100"), repo.mutations)
            assertTrue(adjustments.outbox.dequeueNextRunnable().isEmpty())
            assertTrue(adjustments.api.calls.isEmpty())
        } finally {
            gate.complete(Unit)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun droppedUnverifiedAdjustmentAcceptsUnchangedCanonicalVersionAndReopenStillRequiresRead() = runTest(dispatcher) {
        val adjustments = DebtAdjustmentFixture()
        val canonical = adjustments.debt
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(canonical) }
        val model = DebtDetailViewModel(repo, adjustments.repository)
        var reopened: DebtDetailViewModel? = null
        val gate = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            val id = adjustments.save().getOrThrow()
            adjustments.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            val priorJobs = model.viewModelScope.coroutineContext.job.children.toSet()
            model.recoverAdjustment(adjustments.pending(), drop = true)
            model.viewModelScope.coroutineContext.job.children.single { it !in priorJobs }.join()
            advanceUntilIdle()
            assertTrue(adjustments.outbox.observeStatus().first().failed.none { it.id == id })
            assertTrue(adjustments.outbox.dequeueNextRunnable().isEmpty())
            assertEquals(listOf(canonical.publicId, canonical.publicId), repo.getCalls)
            assertEquals(canonical, model.state.value.debt)
            assertTrue(model.state.value.canWriteActions)
            assertNull(model.state.value.error)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()

            repo.getResult = Result.failure(IllegalStateException("Synthetic unavailable first read"))
            repo.getGate = gate
            val next = DebtDetailViewModel(repo, adjustments.repository).also { reopened = it }
            next.loadDebt(canonical.publicId)
            runCurrent()
            assertFalse(next.state.value.canWriteActions)
            assertNull(next.state.value.debt)
            gate.complete(Unit)
            advanceUntilIdle()
            assertFalse(next.state.value.canWriteActions)
            assertTrue(next.state.value.error != null)
            repo.getGate = null
            repo.getResult = Result.success(canonical)
            next.refresh()
            advanceUntilIdle()
            assertEquals(canonical, next.state.value.debt)
            assertTrue(next.state.value.canWriteActions)
            assertTrue(repo.mutations.isEmpty())
        } finally {
            gate.complete(Unit)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            reopened?.viewModelScope?.coroutineContext?.job?.cancelAndJoin()
        }
    }
}
