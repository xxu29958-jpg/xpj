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
    fun selectedPaymentUsesExistingActionOwnerAndPublishesCanonicalParent() = runTest(dispatcher) {
        val repository = RecordingVoidActions()
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        assertEquals(DebtAction.RepaymentVoid, viewModel.state.value.activeAction)
        assertEquals("payment-7", viewModel.state.value.repaymentToVoid?.publicId)
        viewModel.updateReason("  重复记录  ")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(listOf(VoidAttempt("debt-1", "payment-7", 4, "重复记录")), repository.calls)
        assertEquals(repository.writeResult.getOrThrow(), viewModel.state.value.debt)
        assertNull(viewModel.state.value.activeAction)
        assertNull(viewModel.state.value.repaymentToVoid)
        assertNotNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun failedVoidRetainsTheExactTargetAndReasonForRecovery() = runTest(dispatcher) {
        val repository = RecordingVoidActions().apply {
            writeResult = Result.failure(RepositoryException("欠款已变化，请刷新后再试"))
        }
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateReason("重复记录")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals("payment-7", viewModel.state.value.repaymentToVoid?.publicId)
        assertEquals("重复记录", viewModel.state.value.reasonInput)
        assertNotNull(viewModel.state.value.validationError)
        assertEquals(4L, viewModel.state.value.debt?.rowVersion)
    }

    @Test
    fun inFlightVoidCannotBeDismissedOrSubmittedTwice() = runTest(dispatcher) {
        val repository = RecordingVoidActions().apply { gate = CompletableDeferred() }
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateReason("重复记录")
        viewModel.submit()
        runCurrent()
        viewModel.dismissAction()
        viewModel.submit()
        runCurrent()

        assertEquals(1, repository.calls.size)
        assertTrue(viewModel.state.value.isSubmitting)
        repository.gate!!.complete(repository.writeResult)
        advanceUntilIdle()
    }

    @Test
    fun anotherDebtCannotReceiveLateVoidResult() = runTest(dispatcher) {
        val repository = RecordingVoidActions().apply { gate = CompletableDeferred() }
        val viewModel = DebtDetailViewModel(repository)
        viewModel.loadDebt("debt-1")
        advanceUntilIdle()
        viewModel.openAction(DebtAction.RepaymentVoid, payment())
        viewModel.updateReason("重复记录")
        viewModel.submit()
        runCurrent()
        viewModel.loadDebt("debt-2")
        advanceUntilIdle()
        repository.gate!!.complete(repository.writeResult)
        advanceUntilIdle()

        assertEquals(1, repository.calls.size)
        assertEquals("debt-2", viewModel.state.value.debt?.publicId)
    }

    @Test
    fun memberPaymentsAndViewersDoNotGetDirectVoidAction() = runTest(dispatcher) {
        val member = RecordingVoidActions().apply {
            debt = debt.copy(counterpartyType = "member", sourceType = "bill_split")
        }
        val repositories = listOf(member, RecordingVoidActions(canModify = false))
        for (repository in repositories) {
            val viewModel = DebtDetailViewModel(repository)
            viewModel.loadDebt("debt-1")
            advanceUntilIdle()
            viewModel.openAction(DebtAction.RepaymentVoid, payment())
            assertNull(viewModel.state.value.activeAction)
        }
    }
}

private data class VoidAttempt(val debtId: String, val repaymentId: String, val version: Long, val reason: String)

private class RecordingVoidActions(canModify: Boolean = true) : DebtActions by FakeDebtActions(canModify) {
    var debt = sampleDebt().copy(rowVersion = 4, remainingAmountCents = 0, paidAmountCents = 50_000, status = "cleared")
    var writeResult = Result.success(sampleDebt().copy(
        rowVersion = 5, remainingAmountCents = 20_000, paidAmountCents = 30_000, status = "open",
    ))
    var gate: CompletableDeferred<Result<Debt>>? = null
    val calls = mutableListOf<VoidAttempt>()

    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(debt.copy(publicId = publicId))

    override suspend fun voidRepayment(publicId: String, repaymentPublicId: String, expectedRowVersion: Long, reason: String): Result<Debt> {
        calls += VoidAttempt(publicId, repaymentPublicId, expectedRowVersion, reason)
        return gate?.await() ?: writeResult
    }
}

private fun payment() = DebtRepayment(
    publicId = "payment-7", amountCents = 20_000,
    paidAt = "2026-09-01T09:00:00Z", createdAt = "2026-09-01T09:01:00Z", status = "active",
)
