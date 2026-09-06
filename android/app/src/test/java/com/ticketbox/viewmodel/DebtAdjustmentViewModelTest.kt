package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
class DebtAdjustmentViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun acceptingLocalAdjustmentClosesDraftWithoutInventingCanonicalDebt() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val canonical = repository.getResult.getOrThrow()
        val adjustments = FakeDebtAdjustmentActions()
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "  减免  ")
        viewModel.setAdjustmentSign(increase = false)
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(AdjustmentSaveCall(adjustmentBinding(), canonical, -5_000, "减免"), adjustments.saveCalls.single())
        assertEquals(canonical, viewModel.state.value.debt)
        assertEquals(listOf("debt-1"), repository.getCalls)
        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
        assertFalse(viewModel.state.value.isSubmitting)
        assertEquals(UiText.res(R.string.debt_adjustment_saved), viewModel.state.value.flashMessage)

        val pending = pendingAdjustment()
        adjustments.rows.value = listOf(pending)
        advanceUntilIdle()
        assertEquals(listOf(pending), viewModel.state.value.pendingAdjustments)
        assertEquals(canonical, viewModel.state.value.debt)
        viewModel.openAction(DebtAction.Adjustment)
        assertNull(viewModel.state.value.activeAction)
    }

    @Test
    fun failedDetailReadStillExposesAndRecoversTheOriginalAdjustment() = runTest(dispatcher) {
        val original = pendingAdjustment(status = PendingMutationStatus.Failed)
        val adjustments = FakeDebtAdjustmentActions().apply { rows.value = listOf(original) }
        val repository = AdjustmentDetailActions().apply {
            getResult = Result.failure(RepositoryException("offline"))
        }
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNotNull(viewModel.state.value.error)
        assertEquals(listOf(original), viewModel.state.value.pendingAdjustments)
        viewModel.recoverAdjustment(viewModel.state.value.pendingAdjustments.single(), drop = false)
        advanceUntilIdle()

        assertEquals(AdjustmentRecoveryCall(adjustmentBinding(), original, false), adjustments.recoveryCalls.single())
        assertTrue(adjustments.saveCalls.isEmpty())
        assertEquals(listOf(original), adjustments.rows.value)
        assertEquals(listOf("debt-1"), repository.getCalls)
    }

    @Test
    fun newlyDoneAdjustmentRefreshesOnceWhileHistoricalDoneDoesNotReplay() = runTest(dispatcher) {
        val historical = pendingAdjustment(id = 1, status = PendingMutationStatus.Done)
        val pending = pendingAdjustment(id = 2)
        val adjustments = FakeDebtAdjustmentActions().apply { rows.value = listOf(historical, pending) }
        val repository = AdjustmentDetailActions()
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        assertEquals(listOf("debt-1"), repository.getCalls)
        assertEquals(listOf(pending), viewModel.state.value.pendingAdjustments)

        val committed = repository.getResult.getOrThrow().copy(rowVersion = 8, remainingAmountCents = 45_000)
        repository.getResult = Result.success(committed)
        val done = pending.copy(row = pending.row.copy(status = PendingMutationStatus.Done, completedAt = "2026-09-06T08:01:00Z"))
        adjustments.rows.value = listOf(historical, done)
        advanceUntilIdle()
        assertEquals(2, repository.getCalls.size)
        assertEquals(committed, viewModel.state.value.debt)
        assertTrue(viewModel.state.value.pendingAdjustments.isEmpty())

        // A new queue emission still contains the same completed identities.
        adjustments.rows.value = listOf(done, historical)
        advanceUntilIdle()
        assertEquals(2, repository.getCalls.size)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        assertEquals(3, repository.getCalls.size) // Only the explicit reopen reads again.
        assertEquals(committed, viewModel.state.value.debt)
    }

    @Test
    fun doneBeforeLocalAcknowledgementStillRefreshesCanonicalDebtOnlyOnce() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val adjustments = FakeDebtAdjustmentActions().apply { saveGate = gate }
        val repository = AdjustmentDetailActions()
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        viewModel.setAdjustmentSign(increase = false)
        viewModel.submit()
        runCurrent()

        val committed = repository.getResult.getOrThrow().copy(rowVersion = 8, remainingAmountCents = 45_000)
        repository.getResult = Result.success(committed)
        adjustments.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
        advanceUntilIdle()
        assertEquals(committed, viewModel.state.value.debt)
        assertEquals(2, repository.getCalls.size)

        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(2, repository.getCalls.size)
        assertEquals(committed, viewModel.state.value.debt)
        assertNull(viewModel.state.value.activeAction)
    }

    @Test
    fun sameLedgerIdentitySwitchDropsOldLoadAndDraftBeforeAnotherSave() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val adjustments = FakeDebtAdjustmentActions()
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        val gate = CompletableDeferred<Unit>()
        repository.getGate = gate
        viewModel.refresh()
        runCurrent()

        val original = pendingAdjustment(status = PendingMutationStatus.Failed)
        adjustments.rows.value = listOf(original)
        advanceUntilIdle()
        assertEquals(listOf(original), viewModel.state.value.pendingAdjustments)
        val replacement = adjustmentBinding().copy(ownerKey = "other-owner", sessionGeneration = "session-2", bindingRevision = "binding-2")
        adjustments.access.value = LedgerAccessContext(replacement, canModify = true)
        // Simulate Save before the access observer gets its next turn.
        viewModel.submit()
        runCurrent()
        gate.complete(Unit)
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
        assertTrue(viewModel.state.value.pendingAdjustments.isEmpty())
        assertFalse(viewModel.state.value.isLoading)
        assertTrue(adjustments.saveCalls.isEmpty())
        assertEquals(listOf(original), adjustments.rows.value)
    }

    @Test
    fun lateLocalAcceptanceCannotPublishIntoReplacementBinding() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val gate = CompletableDeferred<Unit>()
        val adjustments = FakeDebtAdjustmentActions().apply { saveGate = gate }
        val viewModel = DebtDetailViewModel(repository, adjustments)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        viewModel.setAdjustmentSign(increase = false)
        viewModel.submit()
        runCurrent()
        assertEquals(adjustmentBinding(), adjustments.saveCalls.single().binding)

        val original = pendingAdjustment()
        adjustments.rows.value = listOf(original)
        adjustments.access.value = LedgerAccessContext(adjustmentBinding().copy(ledgerId = "another-ledger"), canModify = true)
        runCurrent()
        gate.complete(Unit)
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNull(viewModel.state.value.flashMessage)
        assertNull(viewModel.state.value.activeAction)
        assertFalse(viewModel.state.value.isSubmitting)
        assertTrue(viewModel.state.value.pendingAdjustments.isEmpty())
        assertEquals(listOf(original), adjustments.rows.value)
        assertEquals(1, adjustments.saveCalls.size)
    }
}

private class AdjustmentDetailActions : DebtActions by FakeDebtActions() {
    var getResult: Result<Debt> = Result.success(sampleDebt().copy(rowVersion = 7))
    var getGate: CompletableDeferred<Unit>? = null
    val getCalls = mutableListOf<String>()

    override suspend fun getDebt(publicId: String): Result<Debt> {
        getCalls += publicId
        val captured = getResult
        getGate?.await()
        return captured
    }
}
