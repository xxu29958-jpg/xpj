package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.toRequest
import com.ticketbox.domain.model.DebtRepaymentCalendar
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.cancel
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
    fun returningToRepaymentKeepsRawInputAndOriginalTarget() = runTest(dispatcher) {
        val repo = AdjustmentDetailActions().apply { getResult = Result.success(repaymentDebt(5, 50_000)) }
        val writes = FakeDebtWriteActions()
        val saved = SavedStateHandle()
        val clock = Clock.fixed(Instant.parse("2026-09-02T01:00:00Z"), ZoneOffset.UTC)
        var model = DebtDetailViewModel(repo, writes, saved, clock)
        model.loadDebt("d1")
        advanceUntilIdle()
        model.openAction(DebtAction.Repayment)
        val originalKey = model.state.value.repaymentKey
        assertEquals("2026-09-01", model.state.value.paymentTime?.date)
        model.updateActionInput(amount = "0012.00", paymentDate = "2026-09-")
        model.dismissAction()
        model.viewModelScope.cancel()
        val restored = SavedStateHandle(saved.keys().associateWith { saved.get<Any?>(it) })
        repo.getResult = Result.success(repaymentDebt(8, 30_000).copy(repaymentCalendar = DebtRepaymentCalendar(8, "Asia/Tokyo")))
        model = DebtDetailViewModel(repo, writes, restored, clock)
        model.loadDebt("d1")
        advanceUntilIdle()
        model.openAction(DebtAction.Repayment)
        assertEquals("0012.00", model.state.value.amountInput)
        assertEquals(5L, model.state.value.actionTarget?.rowVersion)
        assertEquals("2026-09-", model.state.value.paymentTime?.date)
        assertEquals(3L, model.state.value.paymentTime?.calendarRevision)
        assertEquals("Pacific/Honolulu", model.state.value.paymentTime?.calendarZone)
        assertEquals(originalKey, model.state.value.repaymentKey)
        assertEquals("2026-01-31", model.state.value.actionTarget?.accountingTime?.userLocalDate)
        writes.access.value = requireNotNull(writes.access.value).copy(canModify = false)
        advanceUntilIdle()
        model.dismissAction()
        model.openAction(DebtAction.Repayment)
        assertEquals("0012.00", model.state.value.amountInput)
        assertEquals(originalKey, model.state.value.repaymentKey)
        model.submit()
        advanceUntilIdle()
        assertFalse(model.state.value.canSubmitAction)
        assertTrue(writes.repaymentCalls.isEmpty())
        writes.access.value = requireNotNull(writes.access.value).copy(canModify = true)
        advanceUntilIdle()
        model.updateActionInput(amount = "12.00")
        model.submit()
        advanceUntilIdle()
        assertTrue(writes.repaymentCalls.isEmpty())
        assertEquals(com.ticketbox.domain.model.UiText.res(R.string.calendar_input_invalid_day), model.state.value.validationError)
        model.updateActionInput(paymentDate = "2026-09-01")
        model.submit()
        advanceUntilIdle()
        val sent = writes.repaymentCalls.single()
        assertEquals(originalKey, sent.key)
        assertEquals(5L, sent.debt.rowVersion)
        assertEquals(1_200L, sent.amountCents)
        assertEquals("date_only", sent.paymentTime?.precision)
        assertEquals("2026-09-01", sent.paymentTime?.userLocalDate)
        assertEquals(3L, sent.paymentTime?.calendarRevision)
        assertNull(sent.paymentTime?.instantUtc)
        assertFalse(model.state.value.hasRepaymentDraft)
    }

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
    repaymentCalendar = com.ticketbox.domain.model.DebtRepaymentCalendar(3, "Pacific/Honolulu"),
    accountingTime = com.ticketbox.domain.model.ExpenseAccountingTime("date_only", userLocalDate = "2026-01-31", calendarRevision = 3),
)

private fun confirmedRepayment(call: RepaymentSaveCall): com.ticketbox.data.repository.PendingDebtWrite {
    val payload = com.ticketbox.data.repository.DebtRepaymentPayload(
        revision = 1,
        subject = com.ticketbox.data.repository.DebtWriteSubject(call.debt.publicId,
            call.debt.counterpartyLabel, call.debt.homeCurrencyCode),
        originSessionGeneration = call.binding.sessionGeneration,
        originBindingRevision = call.binding.bindingRevision,
        request = com.ticketbox.data.remote.dto.RepaymentCreateRequestDto(
            call.amountCents, call.debt.rowVersion, timeInput = call.paymentTime?.toRequest()),
    )
    val old = pendingAdjustment(binding = call.binding)
    return old.copy(row = old.row.copy(
        type = com.ticketbox.data.local.PendingMutationType.RecordDebtRepayment,
        targetId = "debt:${call.debt.publicId}", expectedRowVersion = call.debt.rowVersion,
        payloadJson = com.ticketbox.OutboxAdapterGraph().debt.debtRepaymentAdapter.toJson(payload),
        status = com.ticketbox.data.local.PendingMutationStatus.Done,
        idempotencyKey = call.key, completedAt = "2026-09-01T00:01:00Z",
    ), intent = payload)
}
