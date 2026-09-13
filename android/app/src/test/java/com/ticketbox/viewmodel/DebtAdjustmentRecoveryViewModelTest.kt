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
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtAdjustmentRecoveryViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun preStopReadCannotReleaseBarrierAndConfirmedMissingTargetRetiresTheOldWriter() = runTest(dispatcher) {
        val writes = DebtAdjustmentFixture()
        val canonical = writes.debt
        val fresh = canonical.copy(rowVersion = 3L, remainingAmountCents = 53_000L)
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(canonical) }
        val model = DebtDetailViewModel(repo, writes.repository)
        val oldRead = CompletableDeferred<Unit>()
        val newRead = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            val id = writes.save().getOrThrow()
            writes.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            repo.getGate = oldRead
            model.refresh()
            runCurrent()
            repo.getResult = Result.success(fresh)
            repo.getGate = newRead
            writes.repository.recover(writes.binding, writes.pending(), true).getOrThrow()
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
            assertEquals("abandoned", writes.dao.rows.getValue(id).status)
        } finally {
            oldRead.complete(Unit)
            newRead.complete(Unit)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun droppingUnverifiedAdjustmentBlocksOldFoldUntilCanonicalReadRecovers() = runTest(dispatcher) {
        val writes = DebtAdjustmentFixture()
        val canonical = writes.debt
        val fresh = canonical.copy(rowVersion = 3L, remainingAmountCents = 53_000L)
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(canonical) }
        val model = DebtDetailViewModel(repo, writes.repository)
        val gate = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            model.openAction(DebtAction.Repayment)
            model.updateActionInput(amount = "1.00")
            val id = writes.save().getOrThrow()
            writes.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            assertFalse(model.state.value.canWriteActions)
            val original = writes.pending()
            repo.getResult = Result.failure(IllegalStateException("Synthetic unavailable canonical read"))
            repo.getGate = gate

            val priorJobs = model.viewModelScope.coroutineContext.job.children.toSet()
            model.recoverDebtWrite(original, drop = true)
            model.viewModelScope.coroutineContext.job.children.single { it !in priorJobs }.join()
            runCurrent()
            assertTrue(writes.outbox.observeStatus().first().failed.none { it.id == id })
            assertTrue(writes.outbox.dequeueNextRunnable().isEmpty())
            assertEquals(listOf(canonical.publicId, canonical.publicId), repo.getCalls)
            assertFalse(model.state.value.canWriteActions)
            model.submit()
            model.selectKind(DebtKinds.REVOLVING)
            runCurrent()
            assertTrue(repo.mutations.isEmpty(), "Kind writes must remain blocked")
            assertEquals(setOf(id), writes.dao.rows.keys, "The blocked repayment must not publish an original")
            assertEquals(canonical, model.state.value.debt)
            assertEquals("1.00", model.state.value.amountInput)
            gate.complete(Unit)
            advanceUntilIdle()
            assertFalse(model.state.value.canWriteActions)
            assertTrue(model.state.value.error != null)
            assertTrue(model.state.value.writeMessage != null)
            assertNull(model.state.value.flashMessage)

            repo.getGate = null
            repo.getResult = Result.success(fresh)
            model.refresh()
            advanceUntilIdle()
            assertEquals(fresh, model.state.value.debt)
            assertTrue(model.state.value.canWriteActions)
            assertNull(model.state.value.error)
            val priorSubmitJobs = model.viewModelScope.coroutineContext.job.children.toSet()
            model.submit()
            model.viewModelScope.coroutineContext.job.children.single { it !in priorSubmitJobs }.join()
            advanceUntilIdle()
            val published = writes.repository.observeWrites(writes.binding, canonical.publicId).first()
                .single { it.repayment != null }
            val repayment = assertNotNull(published.repayment)
            assertEquals(100L, repayment.request.amountCents)
            assertEquals(3L, repayment.request.expectedRowVersion)
            assertEquals(canonical.publicId, repayment.subject.publicId)
            assertEquals(writes.binding.ownerKey, published.row.ownerKey)
            assertEquals(writes.binding.ledgerId, published.row.ledgerId)
            assertEquals(writes.binding.serverUrl, published.row.serverUrl)
            assertEquals(writes.binding.sessionGeneration, repayment.originSessionGeneration)
            assertEquals(writes.binding.bindingRevision, repayment.originBindingRevision)
            assertTrue(!published.row.idempotencyKey.isNullOrBlank())
            assertTrue(published.row.idempotencyKey != original.row.idempotencyKey)
            assertEquals("pending", published.row.status.wireValue)
            assertEquals(setOf(id, published.row.id), writes.dao.rows.keys)
            assertEquals(published.row.id, writes.outbox.dequeueNextRunnable().single().id)
            assertEquals("abandoned", writes.dao.rows.getValue(id).status)
            assertEquals(fresh, model.state.value.debt)
            assertTrue(repo.mutations.isEmpty())
            assertTrue(writes.api.calls.isEmpty())
        } finally {
            gate.complete(Unit)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun droppedUnverifiedAdjustmentAcceptsUnchangedCanonicalVersionAndReopenStillRequiresRead() = runTest(dispatcher) {
        val writes = DebtAdjustmentFixture()
        val canonical = writes.debt
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(canonical) }
        val model = DebtDetailViewModel(repo, writes.repository)
        var reopened: DebtDetailViewModel? = null
        val gate = CompletableDeferred<Unit>()
        try {
            model.loadDebt(canonical.publicId)
            advanceUntilIdle()
            val id = writes.save().getOrThrow()
            writes.outbox.markFailed(id, "debt_adjustment_response_unverified")
            advanceUntilIdle()
            val priorJobs = model.viewModelScope.coroutineContext.job.children.toSet()
            model.recoverDebtWrite(writes.pending(), drop = true)
            model.viewModelScope.coroutineContext.job.children.single { it !in priorJobs }.join()
            advanceUntilIdle()
            assertTrue(writes.outbox.observeStatus().first().failed.none { it.id == id })
            assertTrue(writes.outbox.dequeueNextRunnable().isEmpty())
            assertEquals(listOf(canonical.publicId, canonical.publicId), repo.getCalls)
            assertEquals(canonical, model.state.value.debt)
            assertTrue(model.state.value.canWriteActions)
            assertNull(model.state.value.error)
            model.viewModelScope.coroutineContext.job.cancelAndJoin()

            repo.getResult = Result.failure(IllegalStateException("Synthetic unavailable first read"))
            repo.getGate = gate
            val next = DebtDetailViewModel(repo, writes.repository).also { reopened = it }
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
