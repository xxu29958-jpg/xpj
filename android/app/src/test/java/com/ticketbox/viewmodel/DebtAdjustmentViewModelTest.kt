package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.DebtRepayment
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
    fun unresolvedOriginalAdjustmentBlocksEveryNewActionAndKindChange() = runTest(dispatcher) {
        for (status in listOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
            PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
            val repository = AdjustmentDetailActions()
            val writes = FakeDebtWriteActions().apply { rows.value = listOf(pendingAdjustment(status = status)) }
            val viewModel = DebtDetailViewModel(repository, writes)
            viewModel.loadDebt("debt-1")
            advanceUntilIdle()

            for (action in DebtAction.entries) {
                viewModel.openAction(action, adjustmentRepayment())
                assertNull(viewModel.state.value.activeAction, "$status must block $action")
            }
            viewModel.selectKind("installment")
            advanceUntilIdle()
            assertTrue(repository.mutations.isEmpty())
            assertTrue(writes.saveCalls.isEmpty())
            assertEquals(listOf(pendingAdjustment(status = status)), viewModel.state.value.pendingWrites)
        }
    }

    @Test
    fun originalAdjustmentArrivingAfterFormOpenedBlocksItsSubmission() = runTest(dispatcher) {
        for (action in DebtAction.entries) {
            val repository = AdjustmentDetailActions()
            val writes = FakeDebtWriteActions()
            val viewModel = DebtDetailViewModel(repository, writes)
            viewModel.loadDebt("debt-1")
            advanceUntilIdle()
            viewModel.openAction(action, adjustmentRepayment())
            viewModel.updateActionInput(amount = "30", reason = "核对原记录")
            assertEquals(action, viewModel.state.value.activeAction)
            writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.InFlight))
            advanceUntilIdle()

            viewModel.submit()
            advanceUntilIdle()

            assertTrue(repository.mutations.isEmpty(), "$action must not send against the old fold")
            assertTrue(writes.saveCalls.isEmpty())
            assertEquals(7L, viewModel.state.value.debt?.rowVersion)
            assertEquals(listOf(pendingAdjustment(status = PendingMutationStatus.InFlight)),
                viewModel.state.value.pendingWrites)
        }
    }

    @Test
    fun deliveredAdjustmentBlocksStaleWritesUntilAuthoritativeRefreshSucceeds() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val writes = FakeDebtWriteActions().apply { rows.value = listOf(pendingAdjustment()) }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        val original = viewModel.state.value.debt
        repository.getResult = Result.failure(RepositoryException("Synthetic unavailable canonical refresh"))
        repository.getGate = CompletableDeferred()
        writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
        runCurrent()
        assertTrue(viewModel.state.value.isLoading)
        viewModel.openAction(DebtAction.Repayment)
        assertNull(viewModel.state.value.activeAction)
        repository.getGate?.complete(Unit)
        advanceUntilIdle()
        assertNotNull(viewModel.state.value.error)
        assertEquals(original, viewModel.state.value.debt)
        for (action in DebtAction.entries) {
            viewModel.openAction(action, adjustmentRepayment())
            assertNull(viewModel.state.value.activeAction)
        }
        viewModel.selectKind("installment")
        advanceUntilIdle()
        assertTrue(repository.mutations.isEmpty())
        assertEquals(PendingMutationStatus.Done, writes.rows.value.single().row.status)

        repository.getGate = null
        repository.getResult = Result.success(requireNotNull(original).copy(rowVersion = 8, remainingAmountCents = 45_000))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(8L, viewModel.state.value.debt?.rowVersion)
        assertEquals(45_000L, viewModel.state.value.debt?.remainingAmountCents)
        viewModel.openAction(DebtAction.Repayment)
        assertEquals(DebtAction.Repayment, viewModel.state.value.activeAction)
        assertTrue(writes.saveCalls.isEmpty())
    }

    @Test
    fun acceptingLocalAdjustmentClosesDraftWithoutInventingCanonicalDebt() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val canonical = repository.getResult.getOrThrow()
        val writes = FakeDebtWriteActions()
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "  减免  ")
        viewModel.updateActionInput(adjustmentIncrease = false)
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(AdjustmentSaveCall(adjustmentBinding(), canonical, -5_000, "减免"), writes.saveCalls.single())
        assertEquals(canonical, viewModel.state.value.debt)
        assertEquals(listOf("debt-1"), repository.getCalls)
        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
        assertFalse(viewModel.state.value.isSubmitting)
        assertEquals(UiText.res(R.string.debt_adjustment_saved), viewModel.state.value.flashMessage)

        val pending = pendingAdjustment()
        writes.rows.value = listOf(pending)
        advanceUntilIdle()
        assertEquals(listOf(pending), viewModel.state.value.pendingWrites)
        assertEquals(canonical, viewModel.state.value.debt)
        viewModel.openAction(DebtAction.Adjustment)
        assertNull(viewModel.state.value.activeAction)
    }

    @Test
    fun failedDetailReadStillExposesAndRecoversTheOriginalAdjustment() = runTest(dispatcher) {
        val original = pendingAdjustment(status = PendingMutationStatus.Failed)
        val writes = FakeDebtWriteActions().apply { rows.value = listOf(original) }
        val repository = AdjustmentDetailActions().apply {
            getResult = Result.failure(RepositoryException("offline"))
        }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNotNull(viewModel.state.value.error)
        assertEquals(listOf(original), viewModel.state.value.pendingWrites)
        viewModel.recoverDebtWrite(viewModel.state.value.pendingWrites.single(), drop = false)
        advanceUntilIdle()

        assertEquals(AdjustmentRecoveryCall(adjustmentBinding(), original, false), writes.recoveryCalls.single())
        assertTrue(writes.saveCalls.isEmpty())
        assertEquals(listOf(original), writes.rows.value)
        assertEquals(listOf("debt-1"), repository.getCalls)
    }

    @Test
    fun newlyDoneAdjustmentRefreshesOnceWhileHistoricalDoneDoesNotReplay() = runTest(dispatcher) {
        val historical = pendingAdjustment(id = 1, status = PendingMutationStatus.Done)
        val pending = pendingAdjustment(id = 2)
        val writes = FakeDebtWriteActions().apply { rows.value = listOf(historical, pending) }
        val repository = AdjustmentDetailActions()
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        assertEquals(listOf("debt-1"), repository.getCalls)
        assertEquals(listOf(pending), viewModel.state.value.pendingWrites)

        val committed = repository.getResult.getOrThrow().copy(rowVersion = 8, remainingAmountCents = 45_000)
        repository.getResult = Result.success(committed)
        val done = pending.copy(row = pending.row.copy(status = PendingMutationStatus.Done, completedAt = "2026-09-06T08:01:00Z"))
        writes.rows.value = listOf(historical, done)
        advanceUntilIdle()
        assertEquals(2, repository.getCalls.size)
        assertEquals(committed, viewModel.state.value.debt)
        assertTrue(viewModel.state.value.pendingWrites.isEmpty())

        // A new queue emission still contains the same completed identities.
        writes.rows.value = listOf(done, historical)
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
        val writes = FakeDebtWriteActions().apply { saveGate = gate }
        val repository = AdjustmentDetailActions()
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        viewModel.updateActionInput(adjustmentIncrease = false)
        viewModel.submit()
        runCurrent()

        val committed = repository.getResult.getOrThrow().copy(rowVersion = 8, remainingAmountCents = 45_000)
        repository.getResult = Result.success(committed)
        writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
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
        val writes = FakeDebtWriteActions()
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        val gate = CompletableDeferred<Unit>()
        repository.getGate = gate
        viewModel.refresh()
        runCurrent()

        val original = pendingAdjustment(status = PendingMutationStatus.Failed)
        writes.rows.value = listOf(original)
        advanceUntilIdle()
        assertEquals(listOf(original), viewModel.state.value.pendingWrites)
        val replacement = adjustmentBinding().copy(ownerKey = "other-owner", sessionGeneration = "session-2", bindingRevision = "binding-2")
        writes.access.value = LedgerAccessContext(replacement, canModify = true)
        // Simulate Save before the access observer gets its next turn.
        viewModel.submit()
        runCurrent()
        gate.complete(Unit)
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNull(viewModel.state.value.activeAction)
        assertEquals("", viewModel.state.value.amountInput)
        assertEquals("", viewModel.state.value.reasonInput)
        assertTrue(viewModel.state.value.pendingWrites.isEmpty())
        assertFalse(viewModel.state.value.isLoading)
        assertTrue(writes.saveCalls.isEmpty())
        assertEquals(listOf(original), writes.rows.value)
    }

    @Test
    fun lateLocalAcceptanceCannotPublishIntoReplacementBinding() = runTest(dispatcher) {
        val repository = AdjustmentDetailActions()
        val gate = CompletableDeferred<Unit>()
        val writes = FakeDebtWriteActions().apply { saveGate = gate }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.Adjustment)
        viewModel.updateActionInput(amount = "50", reason = "减免")
        viewModel.updateActionInput(adjustmentIncrease = false)
        viewModel.submit()
        runCurrent()
        assertEquals(adjustmentBinding(), writes.saveCalls.single().binding)

        val original = pendingAdjustment()
        writes.rows.value = listOf(original)
        writes.access.value = LedgerAccessContext(adjustmentBinding().copy(ledgerId = "another-ledger"), canModify = true)
        runCurrent()
        gate.complete(Unit)
        advanceUntilIdle()

        assertNull(viewModel.state.value.debt)
        assertNull(viewModel.state.value.flashMessage)
        assertNull(viewModel.state.value.activeAction)
        assertFalse(viewModel.state.value.isSubmitting)
        assertTrue(viewModel.state.value.pendingWrites.isEmpty())
        assertEquals(listOf(original), writes.rows.value)
        assertEquals(1, writes.saveCalls.size)
    }
}

private fun adjustmentRepayment() = DebtRepayment(
    publicId = "payment-original", amountCents = 20_000,
    paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z", status = "active",
)
