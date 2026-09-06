package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactCorrectionCohortTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `new root cannot lend its version to loading failed or old-version collection editors`() = edit { fake ->
        fake.useCurrentCollections()
        val oldRoot = fake.baseExpense
        val oldItems = fake.itemsResult.getOrThrow()
        val oldSplits = fake.splitsResult.getOrThrow()
        var waitingItems: CompletableDeferred<Result<ExpenseItems>>? = null
        var waitingSplits: CompletableDeferred<Result<ExpenseSplits>>? = null
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchExpenseItems(id: Long) = waitingItems?.await() ?: fake.itemsResult
            override suspend fun fetchExpenseSplits(id: Long) = waitingSplits?.await() ?: fake.splitsResult
        }
        val vm = ExpenseFactViewModel(oldRoot.id, repository)
        advanceUntilIdle()
        fake.submitCorrection(fake.correctionBinding, oldRoot, ExpenseCorrectionDraft("首个更正", items = emptyList(), splits = emptyList()))
        advanceUntilIdle()
        fake.baseExpense = oldRoot.copy(rowVersion = oldRoot.rowVersion + 1, factRevision = oldRoot.factRevision + 1)
        waitingItems = CompletableDeferred()
        waitingSplits = CompletableDeferred()
        fake.settleCorrection(PendingMutationStatus.Done)
        advanceUntilIdle()

        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertEquals(ExpenseDetailDataLoadState.Loading, vm.uiState.value.itemsLoadState)
        vm.assertCollectionEditorsUnavailable()
        requireNotNull(waitingItems).complete(Result.failure(IllegalStateException("items read failed")))
        requireNotNull(waitingSplits).complete(Result.success(oldSplits))
        advanceUntilIdle()
        assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.itemsLoadState)
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.splitsLoadState)
        vm.assertCollectionEditorsUnavailable()

        waitingItems = null
        waitingSplits = null
        fake.itemsResult = Result.success(oldItems)
        vm.loadExpenseItems()
        advanceUntilIdle()
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.itemsLoadState)
        vm.assertCollectionEditorsUnavailable()
        assertEquals(1, fake.correctCalls)

        fake.useCurrentCollections()
        vm.refreshCorrectionFact()
        advanceUntilIdle()
        vm.closeCorrectionSheet()
        vm.openCorrectionSheet()
        vm.openCorrectionItemsEditor()
        assertTrue(vm.uiState.value.correction.itemsEditorOpen)
        vm.dismissCorrectionItemsEditor()
        vm.openCorrectionSplitsEditor()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.correction.splitEditorOpen)
        assertEquals(fake.baseExpense.rowVersion, vm.uiState.value.expenseItems?.parentRowVersion)
        assertEquals(fake.baseExpense.rowVersion, vm.uiState.value.expenseSplits?.parentRowVersion)
    }

    @Test
    fun `completion while the correction form is open rejects its old baseline at submit`() = edit { fake ->
        fake.useCurrentCollections()
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "正在核对的第二个草稿")
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "我的草稿商家")
        vm.openCorrectionItemsEditor()
        vm.addCorrectionItemRow()
        vm.updateCorrectionItemDraft(0, "草稿明细", "10.00", null)
        vm.adoptCorrectionItems()
        fake.submitCorrection(fake.correctionBinding, fake.baseExpense, ExpenseCorrectionDraft("后台原提交", category = "居家"))
        advanceUntilIdle()
        fake.baseExpense = fake.baseExpense.copy(rowVersion = fake.baseExpense.rowVersion + 1)
        fake.useCurrentCollections()
        fake.settleCorrection(PendingMutationStatus.Done)
        advanceUntilIdle()
        val original = fake.correctionObservations.value.corrections.single()

        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(1, fake.correctCalls, "The already open form must not publish against a superseded baseline")
        assertEquals(original, fake.correctionObservations.value.corrections.single())
        assertTrue(vm.uiState.value.correction.open)
        assertEquals("正在核对的第二个草稿", vm.uiState.value.correction.reason)
        assertEquals("我的草稿商家", vm.uiState.value.correction.merchant)
    }

    private fun ExpenseFactViewModel.assertCollectionEditorsUnavailable() {
        closeCorrectionSheet()
        openCorrectionSheet()
        openCorrectionItemsEditor()
        assertFalse(uiState.value.correction.itemsEditorOpen, "Only a collection matching the frozen root can enter the editor")
        openCorrectionSplitsEditor()
        assertFalse(uiState.value.correction.splitEditorOpen, "A loaded collection can still have the wrong parent version")
    }

    private fun FakeExpenseFactActions.useCurrentCollections() {
        itemsResult = itemsResult.map { it.copy(parentRowVersion = baseExpense.rowVersion) }
        splitsResult = splitsResult.map { it.copy(parentRowVersion = baseExpense.rowVersion) }
    }
}
