package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.TestScope
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

    @Test
    fun `oversized item name remains in the draft and a corrected editor input can save`() = edit { fake ->
        fake.useCurrentCollections()
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Reason, "核对明细名称")
        vm.openCorrectionItemsEditor()
        vm.addCorrectionItemRow()
        vm.updateCorrectionItemDraft(0, "名".repeat(256), null, null)
        vm.adoptCorrectionItems()
        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(0, fake.correctCalls)
        assertTrue(vm.uiState.value.correction.open)
        assertEquals("名".repeat(256), vm.uiState.value.correction.itemDrafts.single().name)
        assertEquals("核对明细名称", vm.uiState.value.correction.reason)
        assertTrue(vm.uiState.value.correction.submitError != null)
        vm.openCorrectionItemsEditor()
        assertEquals("名".repeat(256), vm.uiState.value.correction.itemDrafts.single().name)
        vm.updateCorrectionItemDraft(0, "名".repeat(255), null, null)
        vm.adoptCorrectionItems()
        vm.submitCorrection()
        advanceUntilIdle()

        assertEquals(1, fake.correctCalls)
        assertEquals("名".repeat(255), fake.lastCorrectionDraft?.items?.single()?.name)
        assertFalse(vm.uiState.value.correction.open)
    }

    @Test
    fun `closed split editor response cannot replace an amount entered after reopening`() = edit { fake ->
        fake.useCurrentCollections()
        val members = listOf(fake.member(3L))
        val oldReplies = listOf(
            Result.success(members) to false,
            Result.failure<List<FamilyMember>>(java.io.IOException("obsolete member query")) to false,
            Result.success(members) to true,
        )
        for ((oldResult, adoptBeforeReturn) in oldReplies) {
            assertReopenedEditorPreservesInput(this, fake, members, oldResult, adoptBeforeReturn)
        }
    }

    private fun assertReopenedEditorPreservesInput(
        scope: TestScope,
        fake: FakeExpenseFactActions,
        members: List<FamilyMember>,
        oldResult: Result<List<FamilyMember>>,
        adoptBeforeReturn: Boolean,
    ) {
        val firstMembers = CompletableDeferred<Result<List<FamilyMember>>>()
        var readingForEditor = false
        var editorReads = 0
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> {
                if (!readingForEditor) return Result.success(members)
                editorReads += 1
                return if (editorReads == 1) firstMembers.await() else Result.success(members)
            }
        }
        val vm = ExpenseFactViewModel(fake.baseExpense.id, repository)
        scope.advanceUntilIdle()
        readingForEditor = true
        vm.openCorrectionSheet()
        vm.openCorrectionSplitsEditor()
        scope.advanceUntilIdle()
        assertEquals(1, editorReads)
        assertTrue(vm.uiState.value.correction.splitMembersLoading)

        vm.dismissCorrectionSplitsEditor()
        assertFalse(vm.uiState.value.correction.splitEditorOpen)
        vm.openCorrectionSplitsEditor()
        scope.advanceUntilIdle()
        assertEquals(2, editorReads)
        assertTrue(vm.uiState.value.correction.splitEditorOpen)
        assertFalse(vm.uiState.value.correction.splitMembersLoading)
        vm.updateCorrectionSplitDraft(3L, included = true, amountText = "7.00")
        if (adoptBeforeReturn) {
            vm.adoptCorrectionSplits()
            vm.openCorrectionSplitsEditor()
            scope.advanceUntilIdle()
            assertEquals(2, editorReads, "Adopted drafts reopen without another member request")
            assertTrue(vm.uiState.value.correction.splitEditorOpen)
            assertFalse(vm.uiState.value.correction.splitMembersLoading)
        }
        val editedDrafts = vm.uiState.value.correction.splitDrafts
        assertEquals("7.00", editedDrafts.single().amountText)
        assertTrue(editedDrafts.single().included)
        assertEquals(0, fake.correctCalls)

        val editedState = vm.uiState.value
        assertTrue(firstMembers.complete(oldResult))
        scope.advanceUntilIdle()

        assertEquals(
            "7.00",
            vm.uiState.value.correction.splitDrafts.single().amountText,
            "The member response from the dismissed editor must not erase the new editor's input",
        )
        assertEquals(editedDrafts, vm.uiState.value.correction.splitDrafts)
        assertEquals(editedState, vm.uiState.value, "Obsolete success or failure must not change the current editor")
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
