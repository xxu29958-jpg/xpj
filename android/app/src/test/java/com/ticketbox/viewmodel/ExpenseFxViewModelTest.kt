package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.repository.toDomain
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseSplits
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
import kotlin.test.assertNull
import kotlin.test.assertTrue
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseFxViewModelTest {
    @Test
    fun incompleteForeignInputCannotStartAnFxTask() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions()
            val pending = fake.baseExpense.copy(status = "pending", amountCents = null, originalAmountMinor = null,
                originalCurrencyCode = CurrencyCode.USD, originalCurrency = CurrencyCode.USD, fxStatus = "pending")
            fake.fetchExpenseResponder = { Result.success(pending) }
            val vm = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            vm.retryFx()
            advanceUntilIdle()
            assertEquals(0, fake.fxRetryCalls)
            assertSame(pending, vm.uiState.value.expense)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun taskRefreshNeverAdoptsMoneyOrOccAndExplicitReviewPreservesProtectedDrafts() = runTest {
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
            val fresh = pending.copy(amountCents = 7000, fxStatus = "ready", rowVersion = 2,
                fxRateDate = "2026-09-11", updatedAt = "2026-09-12T10:00:00Z")
            fake.fetchExpenseResponder = { Result.success(fresh) }
            val freshItems = originalItems.copy(parentAmountCents = 7000, parentRowVersion = 2)
            val freshSplits = originalSplits.copy(parentAmountCents = 7000, parentRowVersion = 2)
            fake.fetchItemsResponder = { Result.success(freshItems) }
            fake.fetchSplitsResponder = { Result.success(freshSplits) }
            for (observedTask in listOf(task("completed"), null)) {
                fake.fxTaskResult = Result.success(observedTask)
                vm.refreshFx()
                advanceUntilIdle()
                assertSame(pending, vm.uiState.value.expense)
                assertEquals(observedTask, vm.uiState.value.fx.task)
                assertEquals(0, fake.fxReviewCalls)
                vm.loadFxReview(preserveDraft = true)
                advanceUntilIdle()
                assertSame(pending, vm.uiState.value.expense)
                assertEquals(0, fake.fxReviewCalls)
                assertEquals(originalItems, vm.uiState.value.expenseItems)
                assertEquals(originalSplits, vm.uiState.value.expenseSplits)
            }
            fake.fxTaskResult = Result.success(task("completed"))
            vm.refreshFx()
            advanceUntilIdle()
            fake.fxTaskResult = Result.failure(RepositoryException("读取权限已撤销。", httpStatusCode = 403))
            // Losing write permission alone does not revoke an existing readable result.
            vm.retryFx()
            advanceUntilIdle()
            assertEquals(task("completed"), vm.uiState.value.fx.task)
            assertSame(pending, vm.uiState.value.expense)
            vm.refreshFx()
            advanceUntilIdle()
            assertNull(vm.uiState.value.fx.task, "A denied FX read still presents the previous task result")
            assertSame(pending, vm.uiState.value.expense)
            assertEquals(originalItems, vm.uiState.value.expenseItems)
            assertEquals(originalSplits, vm.uiState.value.expenseSplits)

            fake.fxTaskResult = Result.success(task("completed"))
            vm.refreshFx()
            advanceUntilIdle()
            assertEquals(task("completed"), vm.uiState.value.fx.task)
            vm.loadFxReview(preserveDraft = false)
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
    fun incompleteReviewKeepsTheWholeOriginalUntilAllSnapshotsAgree() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions()
            val vm = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            val original = vm.uiState.value
            val fresh = fake.baseExpense.copy(amountCents = 7000, rowVersion = 2)
            val freshItems = fake.items(parentRowVersion = 2).copy(parentAmountCents = 7000)
            val freshSplits = fake.splits(parentAmountCents = 7000, parentRowVersion = 2)
            fake.fetchExpenseResponder = { Result.success(fresh) }
            fake.fetchItemsResponder = { Result.success(freshItems) }
            val incomplete = listOf(
                Result.failure<ExpenseSplits>(IOException("offline")),
                Result.success(fake.splits()),
            )
            for (result in incomplete) {
                fake.fetchSplitsResponder = { result }
                vm.loadFxReview(preserveDraft = false)
                advanceUntilIdle()
                assertEquals(original.expense, vm.uiState.value.expense)
                assertEquals(original.expenseItems, vm.uiState.value.expenseItems)
                assertEquals(original.expenseSplits, vm.uiState.value.expenseSplits)
                assertTrue(vm.uiState.value.fx.message != null)
                assertFalse(vm.uiState.value.expenseLoading)
                assertFalse(vm.uiState.value.fx.loading)
            }
            fake.fetchSplitsResponder = { Result.success(freshSplits) }
            vm.loadFxReview(preserveDraft = false)
            advanceUntilIdle()
            assertEquals(fresh, vm.uiState.value.expense)
            assertEquals(freshItems, vm.uiState.value.expenseItems)
            assertEquals(freshSplits, vm.uiState.value.expenseSplits)
            assertEquals(0, fake.confirmCalls)
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

    @Test
    fun droppedRegionCanBeExplicitlyReviewedThenConfirmedInTheSameEditor() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions()
            val vm = ExpenseEditViewModel(7L, fake)
            advanceUntilIdle()
            fake.retryOcrResult = Result.success(ExpenseCommandAcceptance(fake.baseExpense, listOf(11L)))
            vm.retryOcr()
            advanceUntilIdle()
            val failed = observedExpenseCommand(11L, fake.baseExpense, PendingMutationType.RetryOcr,
                PendingMutationStatus.Failed, fake.binding)
            fake.commands.value = fake.commands.value.copy(commands = listOf(failed.copy(
                row = failed.row.copy(lastError = "ocr_region_no_text"))))
            advanceUntilIdle()
            vm.loadFxReview(preserveDraft = false)
            advanceUntilIdle()
            assertEquals(0, fake.fxReviewCalls, "Review cannot abandon a retained original")
            assertEquals(listOf(11L), vm.uiState.value.commandRowIds)

            // Sync's explicit Drop removes the original from Room; the editor is still alive.
            fake.commands.value = fake.commands.value.copy(commands = emptyList())
            advanceUntilIdle()
            val beforeReview = vm.uiState.value
            fake.fetchExpenseResponder = { Result.failure(java.io.IOException("offline")) }
            vm.loadFxReview(preserveDraft = false)
            advanceUntilIdle()
            assertEquals(1, fake.fxReviewCalls, "A dropped original must not permanently block review")
            assertEquals(beforeReview.expense, vm.uiState.value.expense)
            assertEquals(beforeReview.formRevision, vm.uiState.value.formRevision)
            assertEquals(listOf(11L), vm.uiState.value.commandRowIds)

            fake.fetchExpenseResponder = { Result.success(fake.baseExpense) }
            vm.loadFxReview(preserveDraft = false)
            advanceUntilIdle()
            assertTrue(vm.uiState.value.commandRowIds.isEmpty())
            assertNull(vm.savedState.get<LongArray>("expense_command_ids"))
            assertNull(vm.savedState.get<String>("expense_command_binding"))
            fake.saveAndConfirmResponder = { _, baseline, _ ->
                assertEquals(fake.baseExpense, baseline)
                Result.success(ExpenseCommandAcceptance(baseline, listOf(12L)))
            }
            vm.confirm(ExpenseDraft(amountCents = 1000L, merchant = null, category = null,
                note = null, expenseTime = null, tags = null, valueScore = null, regretScore = null))
            advanceUntilIdle()
            assertEquals(1, fake.saveAndConfirmCalls)
            assertFalse(vm.consumeDone(), "Local submission is not an accounting receipt")
            fake.commands.value = fake.commands.value.copy(commands = listOf(observedExpenseCommand(
                12L, fake.baseExpense.copy(status = "confirmed"), PendingMutationType.ConfirmExpense,
                PendingMutationStatus.Done, fake.binding)))
            advanceUntilIdle()
            assertTrue(vm.consumeDone())
        } finally { Dispatchers.resetMain() }
    }

    private fun task(status: String) = BackgroundTaskDto(
        publicId = "fx-7", taskType = "expense_fx", status = status,
        createdAt = "2026-09-12T09:00:00Z", sourceExpenseId = 7,
    ).toDomain()
}
