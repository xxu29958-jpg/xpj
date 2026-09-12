package com.ticketbox.viewmodel

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
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

class DebtRepaymentAcceptanceViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun repaymentPublicationRetainsOriginalOccAndAwaitsCanonicalAcceptance() = runTest(dispatcher) {
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(repaymentDebt(5, 50_000)) }
        val writes = FakeDebtWriteActions()
        val viewModel = DebtDetailViewModel(repo, writes)
        viewModel.loadDebt("d1")
        advanceUntilIdle()

        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateActionInput(amount = "100")
        viewModel.submit()
        advanceUntilIdle()

        val call = writes.repaymentCalls.single()
        assertEquals("d1", call.debt.publicId)
        // OCC carrier = the loaded Debt's row_version.
        assertEquals(5L, call.debt.rowVersion)
        assertEquals(10_000L, call.amountCents)
        // Local acceptance closes the form but cannot change the balance or permit a new write.
        assertEquals(5L, viewModel.state.value.debt?.rowVersion)
        assertEquals(50_000L, viewModel.state.value.debt?.remainingAmountCents)
        assertFalse(viewModel.state.value.canWriteActions)
        assertNull(viewModel.state.value.activeAction)
        repo.getResult = Result.success(repaymentDebt(6, 40_000))
        writes.rows.value = listOf(confirmedRepayment(call))
        advanceUntilIdle()
        assertTrue(viewModel.state.value.canWriteActions)
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(40_000L, viewModel.state.value.debt?.remainingAmountCents)
        assertNull(viewModel.state.value.activeAction)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun staleRefreshDoesNotRevertCommittedWrite() = runTest(dispatcher) {
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(repaymentDebt(5, 50_000)) }
        val writes = FakeDebtWriteActions()
        val viewModel = DebtDetailViewModel(repo, writes)
        viewModel.loadDebt("d1")
        advanceUntilIdle() // debt = rv5

        // A slow refresh stalls inside getDebt() (it captured the pre-write rv5 snapshot)...
        val gate = CompletableDeferred<Unit>()
        repo.getGate = gate
        viewModel.refresh()
        runCurrent()

        // Publish the original repayment, then observe its confirmed receipt.
        repo.getGate = null
        viewModel.openAction(DebtAction.Repayment)
        viewModel.updateActionInput(amount = "100")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals(5L, writes.repaymentCalls.single().debt.rowVersion)
        assertEquals(10_000L, writes.repaymentCalls.single().amountCents)
        assertEquals(5L, viewModel.state.value.debt?.rowVersion)
        repo.getResult = Result.success(repaymentDebt(6, 40_000))
        writes.rows.value = listOf(confirmedRepayment(writes.repaymentCalls.single()))
        advanceUntilIdle()
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)

        // Release the now-stale refresh; its rv5 snapshot must NOT revert the committed write — else
        // the next write's OCC carrier would be stale (→ a 409).
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(6L, viewModel.state.value.debt?.rowVersion)
        assertEquals(40_000L, viewModel.state.value.debt?.remainingAmountCents)
    }

}

private fun repaymentDebt(version: Long, remaining: Long) = sampleDebt("d1").copy(
    rowVersion = version, remainingAmountCents = remaining, paidAmountCents = 50_000L - remaining,
)

private fun confirmedRepayment(call: RepaymentSaveCall): com.ticketbox.data.repository.PendingDebtWrite {
    val payload = com.ticketbox.data.repository.DebtRepaymentPayload(
        revision = 1,
        subject = com.ticketbox.data.repository.DebtWriteSubject(call.debt.publicId,
            call.debt.counterpartyLabel, call.debt.homeCurrencyCode),
        originSessionGeneration = call.binding.sessionGeneration,
        originBindingRevision = call.binding.bindingRevision,
        request = com.ticketbox.data.remote.dto.RepaymentCreateRequestDto(
            call.amountCents, call.debt.rowVersion, "2026-09-01T00:00:00Z"),
    )
    val old = pendingAdjustment(binding = call.binding)
    return old.copy(row = old.row.copy(
        type = com.ticketbox.data.local.PendingMutationType.RecordDebtRepayment,
        targetId = "debt:${call.debt.publicId}", expectedRowVersion = call.debt.rowVersion,
        payloadJson = com.ticketbox.OutboxAdapterGraph().debtRepaymentAdapter.toJson(payload),
        status = com.ticketbox.data.local.PendingMutationStatus.Done,
        idempotencyKey = "original-repayment", completedAt = "2026-09-01T00:01:00Z",
    ), intent = payload)
}
