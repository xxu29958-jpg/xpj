package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtRepayment
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
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtRepaymentVoidViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun selectedPaymentPublishesOriginalThroughDurableOwnerBeforeCanonicalRefresh() = runTest(dispatcher) {
        val repository = RecordingVoidActions()
        val writes = FakeDebtWriteActions()
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        assertEquals(DebtAction.RepaymentVoid, viewModel.state.value.activeAction)
        assertEquals("payment-7", viewModel.state.value.repaymentToVoid?.publicId)
        viewModel.updateActionInput(reason = "  重复记录  ")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals("payment-7", writes.voidCalls.single().repaymentPublicId)
        assertEquals("重复记录", writes.voidCalls.single().reason)
        assertEquals(4L, writes.voidCalls.single().debt.rowVersion)
        assertEquals(repository.debt.copy(publicId = "debt-1"), viewModel.state.value.debt)
        assertNull(viewModel.state.value.activeAction)
        assertNull(viewModel.state.value.repaymentToVoid)
        assertNotNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun failedVoidRetainsTheExactTargetAndReasonForRecovery() = runTest(dispatcher) {
        val repository = RecordingVoidActions()
        val writes = FakeDebtWriteActions().apply { saveResult = Result.failure(RepositoryException("本机保存失败")) }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateActionInput(reason = "重复记录")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals("payment-7", viewModel.state.value.repaymentToVoid?.publicId)
        assertEquals("重复记录", viewModel.state.value.reasonInput)
        assertNotNull(viewModel.state.value.validationError)
        assertEquals(4L, viewModel.state.value.debt?.rowVersion)
    }

    @Test
    fun inFlightVoidCannotBeDismissedOrSubmittedTwice() = runTest(dispatcher) {
        val repository = RecordingVoidActions()
        val writes = FakeDebtWriteActions().apply { saveGate = CompletableDeferred() }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateActionInput(reason = "重复记录")
        viewModel.submit()
        runCurrent()
        viewModel.dismissAction()
        viewModel.submit()
        runCurrent()

        assertEquals(1, writes.voidCalls.size)
        assertTrue(viewModel.state.value.isSubmitting)
        writes.saveGate!!.complete(Unit)
        advanceUntilIdle()
    }

    @Test
    fun anotherDebtCannotReceiveLateVoidResult() = runTest(dispatcher) {
        val repository = RecordingVoidActions()
        val writes = FakeDebtWriteActions().apply { saveGate = CompletableDeferred() }
        val viewModel = DebtDetailViewModel(repository, writes)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateActionInput(reason = "重复记录")
        viewModel.submit()
        runCurrent()
        viewModel.loadDebt("debt-2")
        advanceUntilIdle()
        writes.saveGate!!.complete(Unit)
        advanceUntilIdle()

        assertEquals(1, writes.voidCalls.size)
        assertEquals("debt-2", viewModel.state.value.debt?.publicId)
    }

    @Test
    fun memberPaymentsAndViewersDoNotGetDirectVoidAction() = runTest(dispatcher) {
        val member = RecordingVoidActions().apply {
            debt = debt.copy(counterpartyType = "member", sourceType = "bill_split")
        }
        val repositories = listOf(member, RecordingVoidActions(canModify = false))
        for (repository in repositories) {
            val writes = FakeDebtWriteActions()
            val viewModel = DebtDetailViewModel(repository, writes)
            viewModel.loadDebt("debt-1")
            advanceUntilIdle()
            viewModel.openAction(DebtAction.RepaymentVoid, payment())
            assertNull(viewModel.state.value.activeAction)
        }
    }
}

private class RecordingVoidActions(canModify: Boolean = true) : DebtActions by FakeDebtActions(canModify) {
    var debt = sampleDebt().copy(rowVersion = 4, remainingAmountCents = 0, paidAmountCents = 50_000, status = "cleared")
    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(debt.copy(publicId = publicId))


}

private fun payment() = DebtRepayment(
    publicId = "payment-7", amountCents = 20_000,
    paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z", status = "active",
)
