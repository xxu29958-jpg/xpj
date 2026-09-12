package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.PendingPrimaryReviewAction
import com.ticketbox.domain.model.pendingPrimaryReviewAction
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseFxViewModelTest {
    @Test
    fun taskRefreshNeverAdoptsMoneyOrOccAndExplicitReviewRequiresSavedDraft() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions()
            val pending = fake.baseExpense.copy(amountCents = null, originalAmountMinor = 1000,
                originalCurrencyCode = CurrencyCode.USD, originalCurrency = CurrencyCode.USD, category = "餐饮", fxStatus = "pending")
            fake.fetchExpenseResponder = { Result.success(pending) }
            val originalItems = fake.items().copy(parentAmountCents = null)
            val originalSplits = fake.splits(parentAmountCents = null)
            fake.fetchItemsResponder = { Result.success(originalItems) }
            fake.fetchSplitsResponder = { Result.success(originalSplits) }
            val vm = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            fake.fxTaskResult = Result.success(task("completed"))
            val fresh = pending.copy(amountCents = 7000, fxStatus = "ready", rowVersion = 2,
                fxRateDate = "2026-09-11", updatedAt = "2026-09-12T10:00:00Z")
            fake.fetchExpenseResponder = { Result.success(fresh) }
            val freshItems = originalItems.copy(parentAmountCents = 7000, parentRowVersion = 2)
            val freshSplits = originalSplits.copy(parentAmountCents = 7000, parentRowVersion = 2)
            fake.fetchItemsResponder = { Result.success(freshItems) }
            fake.fetchSplitsResponder = { Result.success(freshSplits) }
            vm.refreshFx()
            advanceUntilIdle()
            assertSame(pending, vm.uiState.value.expense)
            assertEquals("completed", vm.uiState.value.fx.task?.status)
            assertEquals(0, fake.fxReviewCalls)
            vm.loadFxReview(hasDraftChanges = true)
            advanceUntilIdle()
            assertSame(pending, vm.uiState.value.expense)
            assertEquals(0, fake.fxReviewCalls)
            assertEquals(originalItems, vm.uiState.value.expenseItems)
            assertEquals(originalSplits, vm.uiState.value.expenseSplits)
            vm.loadFxReview(hasDraftChanges = false)
            advanceUntilIdle()
            assertEquals(fresh, vm.uiState.value.expense)
            assertEquals(freshItems, vm.uiState.value.expenseItems)
            assertEquals(freshSplits, vm.uiState.value.expenseSplits)
            assertEquals(1, fake.fxReviewCalls)
            assertEquals(0, fake.confirmCalls)
            assertFalse(vm.uiState.value.done)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun failedReadKeepsOriginalAndViewerCannotStartFxTask() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions().apply { canModifyLedgerFlag = false }
            val vm = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            fake.fxTaskResult = Result.failure(IOException("offline"))
            vm.refreshFx()
            advanceUntilIdle()
            assertSame(fake.baseExpense, vm.uiState.value.expense)
            assertTrue(vm.uiState.value.fx.message != null)
            assertFalse(vm.uiState.value.fx.loading)
            vm.retryFx()
            advanceUntilIdle()
            assertEquals(0, fake.fxRetryCalls)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun originalMoneyIsFxRecoveryRatherThanMissingAmountOrReadyToConfirm() {
        val pending = FakeExpenseEditActions().baseExpense.copy(amountCents = null, originalAmountMinor = 1000,
            originalCurrencyCode = CurrencyCode.USD, originalCurrency = CurrencyCode.USD, category = "餐饮", fxStatus = "pending")
        assertEquals(PendingPrimaryReviewAction.FxPending, pendingPrimaryReviewAction(pending))
        assertTrue(applyNeedsReviewFilter(listOf(pending), NeedsReviewFilter.NeedsAmount).isEmpty())
        assertTrue(applyNeedsReviewFilter(listOf(pending), NeedsReviewFilter.ReadyToConfirm).isEmpty())
        assertEquals(listOf(pending), applyNeedsReviewFilter(listOf(pending), NeedsReviewFilter.NeedsFx))
    }

    private fun task(status: String) = BackgroundTaskDto(
        publicId = "fx-7", taskType = "expense_fx", status = status,
        createdAt = "2026-09-12T09:00:00Z", sourceExpenseId = 7,
    ).toDomain()
}
