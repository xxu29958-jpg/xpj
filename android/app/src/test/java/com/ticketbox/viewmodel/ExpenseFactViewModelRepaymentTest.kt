package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Expense
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.TestScope

/** A1: repayment capture is consumed by the confirmed fact owner, not the legacy editor. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelRepaymentTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `successful capture opens the real review destination once`() = edit { fake ->
        fake.repaymentDraftResult = { Result.success(fake.repaymentDraft()) }
        val vm = viewModel(fake)

        vm.createRepaymentDraftFromExpense()
        advanceUntilIdle()

        assertEquals(1, fake.repaymentDraftCalls)
        assertEquals(fake.baseExpense, fake.repaymentDraftExpense)
        assertFalse(vm.uiState.value.repaymentDraftCreating)
        assertEquals("rd-1", vm.consumeOpenRepaymentDraftPublicId())
        assertNull(vm.consumeOpenRepaymentDraftPublicId())
    }

    @Test
    fun `read only fact never starts repayment capture`() = edit { fake ->
        fake.canModifyLedgerFlag = false
        val vm = viewModel(fake)

        vm.createRepaymentDraftFromExpense()
        advanceUntilIdle()

        assertEquals(0, fake.repaymentDraftCalls)
        assertNull(vm.uiState.value.openRepaymentDraftPublicId)
    }

    @Test
    fun `unresolved corrections cannot create a repayment draft from the old fact`() = edit { fake ->
        assertUnresolvedCorrectionBlocksCapture(this, fake)
    }

    private suspend fun assertUnresolvedCorrectionBlocksCapture(scope: TestScope, fake: FakeExpenseFactActions) {
        fake.repaymentDraftResult = { Result.success(fake.repaymentDraft()) }
        val vm = scope.viewModel(fake)
        submitAmountCorrection(scope, vm)
        val original = vm.uiState.value.corrections.single()
        val statuses = listOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
            PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
        val observed = linkedMapOf<PendingMutationStatus, Pair<Int, String?>>()
        for (status in statuses) {
            fake.settleCorrection(status)
            scope.advanceUntilIdle()
            val before = fake.repaymentDraftCalls
            vm.createRepaymentDraftFromExpense()
            scope.advanceUntilIdle()
            observed[status] = (fake.repaymentDraftCalls - before) to vm.consumeOpenRepaymentDraftPublicId()
        }

        val expected: Map<PendingMutationStatus, Pair<Int, String?>> = statuses.associateWith { 0 to null }
        assertEquals(expected, observed)
        assertEquals(1_000L, vm.uiState.value.expense?.amountCents)
        assertEquals(original.intent, vm.uiState.value.corrections.single().intent)
        assertEquals(original.row.idempotencyKey, vm.uiState.value.corrections.single().row.idempotencyKey)
        assertEquals(1, fake.correctCalls)
    }

    @Test
    fun `delivered correction blocks repayment until authoritative refresh is adopted`() = edit { fake ->
        assertCaptureWaitsForAuthoritativeRefresh(this, fake)
    }

    private suspend fun assertCaptureWaitsForAuthoritativeRefresh(scope: TestScope, fake: FakeExpenseFactActions) {
        val refresh = CompletableDeferred<Result<Expense>>()
        val cachedBeforeCorrection = fake.baseExpense
        var holdRefresh = false
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> = Result.success(cachedBeforeCorrection)
            override suspend fun fetchExpense(id: Long): Result<Expense> =
                if (holdRefresh) refresh.await() else fake.fetchExpense(id)
        }
        fake.repaymentDraftResult = { Result.success(fake.repaymentDraft()) }
        val vm = ExpenseFactViewModel(expenseId = fake.baseExpense.id, repository = repository)
        scope.advanceUntilIdle()
        submitAmountCorrection(scope, vm)
        fake.baseExpense = fake.baseExpense.copy(
            amountCents = 1_400L, homeAmountCents = 1_400L, originalAmountMinor = 1_400L,
            rowVersion = 2L, factRevision = 2L,
        )
        holdRefresh = true
        fake.settleCorrection(PendingMutationStatus.Done)
        scope.advanceUntilIdle()
        assertTrue(vm.uiState.value.corrections.single().delivered)
        assertEquals(ExpenseDetailDataLoadState.Loading, vm.uiState.value.expenseLoadState)
        assertEquals(1_000L, vm.uiState.value.expense?.amountCents)
        vm.createRepaymentDraftFromExpense()
        scope.advanceUntilIdle()
        val whileLoading = fake.repaymentDraftCalls to vm.consumeOpenRepaymentDraftPublicId()

        refresh.complete(Result.failure(RepositoryException("refresh offline")))
        scope.advanceUntilIdle()
        assertTrue(vm.uiState.value.expenseStale)
        vm.createRepaymentDraftFromExpense()
        scope.advanceUntilIdle()
        val afterFailure = fake.repaymentDraftCalls to vm.consumeOpenRepaymentDraftPublicId()
        holdRefresh = false
        vm.retryLoadExpense()
        scope.advanceUntilIdle()
        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.expenseLoadState)
        vm.createRepaymentDraftFromExpense()
        scope.advanceUntilIdle()

        assertEquals(0 to null, whileLoading)
        assertEquals(0 to null, afterFailure)
        assertEquals(1, fake.repaymentDraftCalls)
        assertEquals(fake.baseExpense, fake.repaymentDraftExpense)
        assertEquals("rd-1", vm.consumeOpenRepaymentDraftPublicId())
        assertNull(vm.consumeOpenRepaymentDraftPublicId())
        assertEquals(1, fake.correctCalls, "Refreshing the fact must not replay the correction")
    }

    private suspend fun submitAmountCorrection(scope: TestScope, vm: ExpenseFactViewModel) {
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Amount, "14.00")
        vm.updateCorrectionField(CorrectionScalarField.Reason, "Correct the captured amount")
        vm.submitCorrection()
        scope.advanceUntilIdle()
        assertEquals(PendingMutationStatus.Pending, vm.uiState.value.corrections.single().row.status)
    }
}
