package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseEditActions
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.ExpenseCommandObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.MutableStateFlow
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.data.repository.ReplaceItemsOutcome
import com.ticketbox.data.repository.ReplaceSplitsOutcome
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/**
 * 架构债 #5 — ExpenseEditViewModel 核心契约单元测试。
 *
 * 该 ViewModel 此前直接依赖 final 的 [com.ticketbox.data.repository.ExpenseRepository]
 * 门面、无法 fake，是 viewmodel/ 里唯一零单测的大 VM。本切片抽出
 * [ExpenseEditActions] 接口（PendingReviewActions 先例模式）后补上：
 * save / confirm 的持久化接收、独立完成观察、原 baseline 复核、金额守卫、
 * saveSplits 的 ADR-0042 P1 防数据丢失守卫、只读门、
 * 均分对 disabled 固定份额的扣除。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseEditViewModelTest {

    private fun edit(block: suspend TestScope.(FakeExpenseEditActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(FakeExpenseEditActions())
        } finally {
            // Drain init's five load coroutines before resetMain so runTest's
            // teardown never touches an unset Dispatchers.Main (same hygiene
            // as PendingViewModelReviewTestBase.review).
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    private fun TestScope.viewModel(fake: FakeExpenseEditActions): ExpenseEditViewModel {
        val vm = ExpenseEditViewModel(expenseId = 7L, repository = fake)
        advanceUntilIdle() // let init's loads settle against the fake defaults
        return vm
    }

    private fun draft(
        amountCents: Long? = null,
        merchant: String? = null,
        manualExchangeRate: String? = null,
    ): ExpenseDraft = ExpenseDraft(
        amountCents = amountCents,
        manualExchangeRate = manualExchangeRate,
        merchant = merchant,
        category = null,
        note = null,
        expenseTime = null,
        tags = null,
        valueScore = null,
        regretScore = null,
    )

    @Test
    fun negativeIdLoadsPendingRowFromLocalCacheAndSkipsServerSubLoads() = edit { fake ->
        // issue #65 slice 5: a not-yet-synced offline create has a NEGATIVE local
        // id the server can't resolve — the VM must load it from the local cache,
        // and skip the server-only image / items / splits loads (else they 404 and
        // show spurious "load failed" messages).
        val pending = fake.baseExpense.copy(id = -5L, clientRef = "ref-x", pendingSync = true)
        fake.localCacheResponder = { id ->
            if (id == -5L) Result.success(pending) else Result.failure(IllegalStateException("unexpected id $id"))
        }

        val vm = ExpenseEditViewModel(expenseId = -5L, repository = fake)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(pending, state.expense, "a negative id must load from the local cache")
        assertEquals(1, fake.localCacheCalls, "the local-cache path must be used, not the server fetch")
        assertNull(state.thumbnail, "no server image load for a pending row")
        assertEquals(0, fake.fetchItemsCalls, "no server items load for a pending row")
        assertEquals(0, fake.fetchSplitsCalls, "no server splits load for a pending row")
        assertEquals(ExpenseDetailDataLoadState.Loaded, state.itemsLoadState)
        assertEquals(ExpenseDetailDataLoadState.Loaded, state.splitsLoadState)
        val items = assertNotNull(state.expenseItems, "local-only pending rows expose an explicit empty item model")
        val splits = assertNotNull(state.expenseSplits, "local-only pending rows expose an explicit empty split model")
        assertTrue(items.items.isEmpty())
        assertTrue(splits.splits.isEmpty())
        assertEquals(pending.id, items.expenseId)
        assertEquals(pending.id, splits.expenseId)
        assertEquals(pending.amountCents, items.parentAmountCents)
        assertEquals(pending.amountCents, splits.parentAmountCents)
        assertEquals(pending.rowVersion, items.parentRowVersion)
        assertEquals(pending.rowVersion, splits.parentRowVersion)
    }

    @Test
    fun detailChildLoadsMarkSuccessfulEmptyResponsesAsLoaded() = edit { fake ->
        val vm = viewModel(fake)

        val state = vm.uiState.value
        assertEquals(ExpenseDetailDataLoadState.Loaded, state.itemsLoadState)
        assertEquals(ExpenseDetailDataLoadState.Loaded, state.splitsLoadState)
        val items = assertNotNull(state.expenseItems)
        val splits = assertNotNull(state.expenseSplits)
        assertTrue(items.items.isEmpty())
        assertTrue(splits.splits.isEmpty())
        assertNull(state.itemsMessage)
        assertNull(state.splitsMessage)
        assertEquals(1, fake.fetchItemsCalls)
        assertEquals(1, fake.fetchSplitsCalls)
    }

    @Test
    fun detailChildLoadFailuresStayFailedInsteadOfLoadedEmpty() = edit { fake ->
        fake.fetchItemsResponder = { Result.failure(RuntimeException("items failed")) }
        fake.fetchSplitsResponder = { Result.failure(RuntimeException("splits failed")) }

        val vm = viewModel(fake)

        val state = vm.uiState.value
        assertEquals(ExpenseDetailDataLoadState.Failed, state.itemsLoadState)
        assertEquals(ExpenseDetailDataLoadState.Failed, state.splitsLoadState)
        assertNull(state.expenseItems)
        assertNull(state.expenseSplits)
        assertNotNull(state.itemsMessage)
        assertNotNull(state.splitsMessage)
        assertEquals(MessageTone.Danger, state.itemsMessageTone)
        assertEquals(MessageTone.Danger, state.splitsMessageTone)
        assertEquals(1, fake.fetchItemsCalls)
        assertEquals(1, fake.fetchSplitsCalls)
    }

    @Test
    fun acceptedSaveKeepsReviewedVersionAndStaysOpenUntilExplicitBaselineReview() = edit { fake ->
        val vm = viewModel(fake)
        val accepted = fake.baseExpense.copy(merchant = "新商家", pendingSync = true)
        fake.saveOfflineResponder = { _, _, baseline ->
            assertEquals(fake.baseExpense, baseline)
            Result.success(ExpenseCommandAcceptance(accepted, listOf(11L)))
        }
        vm.save(draft(merchant = "新商家"))
        advanceUntilIdle()
        assertEquals(accepted, vm.uiState.value.expense)
        assertEquals(listOf(11L), vm.uiState.value.commandRowIds)
        assertEquals(listOf(fake.binding), fake.submittedBindings)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertFalse(vm.uiState.value.commandsCompleted)
        assertFalse(vm.consumeDone())

        val originalFormRevision = vm.uiState.value.formRevision
        fake.commands.value = fake.commands.value.copy(commands = listOf(observedExpenseCommand(
            11L, accepted, PendingMutationType.PatchExpense, PendingMutationStatus.Done, fake.binding,
        )))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.commandsCompleted)
        assertEquals(accepted, vm.uiState.value.expense)
        assertEquals(originalFormRevision, vm.uiState.value.formRevision)
        assertFalse(vm.consumeDone())
        vm.save(draft(merchant = "later draft"))
        advanceUntilIdle()
        assertEquals(1, fake.saveCalls, "Done alone cannot authorize resubmission against the old baseline")

        val canonical = accepted.copy(rowVersion = 2L, pendingSync = false)
        fake.fetchExpenseResponder = { Result.success(canonical) }
        fake.fetchItemsResponder = { Result.success(fake.items(parentRowVersion = 2L)) }
        fake.fetchSplitsResponder = { Result.success(fake.splits(parentRowVersion = 2L)) }
        vm.loadFxReview(preserveDraft = false)
        advanceUntilIdle()
        assertEquals(canonical, vm.uiState.value.expense)
        assertEquals(originalFormRevision + 1, vm.uiState.value.formRevision)
        assertTrue(vm.uiState.value.commandRowIds.isEmpty())
        fake.saveOfflineResponder = { _, _, baseline ->
            assertEquals(canonical, baseline)
            Result.success(ExpenseCommandAcceptance(canonical, listOf(12L)))
        }
        vm.save(draft(merchant = "later draft"))
        advanceUntilIdle()
        assertEquals(2, fake.saveCalls)
    }

    @Test
    fun queuedSaveSurfacesPendingIntentWithoutCompletingTheEditor() = edit { fake ->
        val vm = viewModel(fake)
        val queued = fake.baseExpense.copy(merchant = "离线商家", pendingSync = true)
        fake.saveOfflineResponder = { _, _, _ -> Result.success(ExpenseCommandAcceptance(queued, listOf(11L))) }
        vm.save(draft(merchant = "离线商家"))
        advanceUntilIdle()
        assertEquals(queued, vm.uiState.value.expense)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
        assertFalse(vm.uiState.value.saving)
        assertFalse(vm.uiState.value.commandsCompleted)
        assertFalse(vm.consumeDone())
    }

    @Test
    fun saveFailureKeepsPageOpenWithError() = edit { fake ->
        val vm = viewModel(fake)
        fake.saveOfflineResponder = { _, _, _ -> Result.failure(RuntimeException("boom")) }

        vm.save(draft(merchant = "x"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.saving)
        assertNotNull(state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
        assertFalse(vm.consumeDone())
    }

    @Test
    fun manualRateCompletionRequiresCanonicalReviewBeforeDisplayingConvertedMoney() = edit { fake ->
        val pendingFx = fake.baseExpense.copy(amountCents = null, homeAmountCents = null,
            originalCurrency = CurrencyCode.JPY, originalCurrencyCode = CurrencyCode.JPY,
            originalCurrencyCodeRaw = "JPY", originalAmountMinor = 1200L,
            fxRate = null, exchangeRateToCny = null, fxStatus = FxContract.StatusPending)
        fake.fetchExpenseResponder = { Result.success(pendingFx) }
        val vm = viewModel(fake)
        fake.saveOfflineResponder = { _, _, _ -> Result.success(ExpenseCommandAcceptance(pendingFx, listOf(11L))) }
        vm.save(draft(manualExchangeRate = "0.048"))
        advanceUntilIdle()
        fake.commands.value = fake.commands.value.copy(commands = listOf(observedExpenseCommand(
            11L, pendingFx, PendingMutationType.PatchExpense, PendingMutationStatus.Done, fake.binding,
        )))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.commandsCompleted)
        assertEquals(pendingFx, vm.uiState.value.expense)
        assertNull(vm.uiState.value.expense?.homeAmountCents)
        assertFalse(vm.consumeDone())
        assertEquals(0, fake.confirmCalls)
        assertEquals(0, fake.saveAndConfirmCalls)
    }

    @Test
    fun manualRateQueuedSaveKeepsPendingStateOpenUntilServerCalculation() = edit { fake ->
        val pendingFx = fake.baseExpense.copy(
            amountCents = null,
            homeAmountCents = null,
            originalCurrency = CurrencyCode.USD,
            originalCurrencyCode = CurrencyCode.USD,
            originalCurrencyCodeRaw = "USD",
            originalAmountMinor = 1200L,
            fxRate = null,
            exchangeRateToCny = null,
            fxStatus = FxContract.StatusPending,
        )
        fake.fetchExpenseResponder = { Result.success(pendingFx) }
        val vm = viewModel(fake)
        fake.saveOfflineResponder = { _, _, _ -> Result.success(ExpenseCommandAcceptance(pendingFx, listOf(11L))) }

        vm.save(draft(manualExchangeRate = "7.20"))
        advanceUntilIdle()

        assertEquals(FxContract.StatusPending, vm.uiState.value.expense?.fxStatus)
        assertNull(vm.uiState.value.expense?.homeAmountCents)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
        assertFalse(vm.consumeDone(), "queued rate intent must remain open and visibly unconfirmed")
        assertEquals(0, fake.confirmCalls)
    }

    @Test
    fun confirmRequiresAnAmount() = edit { fake ->
        val vm = viewModel(fake)

        vm.confirm(draft())
        advanceUntilIdle()

        assertNotNull(vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertEquals(0, fake.saveCalls)
        assertEquals(0, fake.confirmCalls)
        assertFalse(vm.consumeDone())
    }

    @Test
    fun confirmAdmitsSaveAndConfirmTogetherWithTheReviewedBaseline() = edit { fake ->
        val vm = viewModel(fake)
        val reviewed = fake.baseExpense
        fake.saveAndConfirmResponder = { binding, expense, input ->
            assertEquals(fake.binding, binding)
            assertEquals(reviewed, expense)
            assertEquals(1200L, input.amountCents)
            Result.success(ExpenseCommandAcceptance(reviewed, listOf(21L, 22L)))
        }
        vm.confirm(draft(amountCents = 1200L))
        advanceUntilIdle()
        assertEquals(1, fake.saveAndConfirmCalls)
        assertEquals(0, fake.saveCalls)
        assertEquals(0, fake.confirmCalls)
        assertEquals("pending", vm.uiState.value.expense?.status)
        assertEquals(listOf(21L, 22L), vm.uiState.value.commandRowIds)
        assertFalse(vm.consumeDone())

        val saved = observedExpenseCommand(21L, reviewed, PendingMutationType.PatchExpense,
            PendingMutationStatus.Done, fake.binding)
        val confirming = observedExpenseCommand(22L, reviewed, PendingMutationType.ConfirmExpense,
            PendingMutationStatus.Pending, fake.binding)
        fake.commands.value = fake.commands.value.copy(commands = listOf(saved, confirming))
        advanceUntilIdle()
        assertFalse(vm.uiState.value.commandsCompleted, "a completed save is not a completed confirmation")
        fake.commands.value = fake.commands.value.copy(commands = listOf(saved,
            confirming.copy(row = confirming.row.copy(status = PendingMutationStatus.Done))))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.commandsCompleted)
        assertTrue(vm.uiState.value.done)
        assertEquals(reviewed, vm.uiState.value.expense, "receipt observation must preserve the raw form baseline")
    }

    @Test
    fun confirmAdmissionFailureRetainsTheOriginalReviewedExpense() = edit { fake ->
        val vm = viewModel(fake)
        fake.saveAndConfirmResponder = { _, _, _ -> Result.failure(RuntimeException("admission refused")) }
        vm.confirm(draft(amountCents = 500L))
        advanceUntilIdle()
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertFalse(vm.uiState.value.saving)
        assertFalse(vm.consumeDone())
        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertTrue(vm.uiState.value.commandRowIds.isEmpty())
        assertEquals(0, fake.saveCalls)
        assertEquals(0, fake.confirmCalls)
    }

    @Test
    fun queuedConfirmConflictKeepsBothOriginalRowsForRecovery() = edit { fake ->
        val vm = viewModel(fake)
        fake.saveAndConfirmResponder = { _, expense, _ ->
            Result.success(ExpenseCommandAcceptance(expense, listOf(21L, 22L)))
        }
        vm.confirm(draft(amountCents = 1200L))
        advanceUntilIdle()
        fake.commands.value = fake.commands.value.copy(commands = listOf(
            observedExpenseCommand(21L, fake.baseExpense, PendingMutationType.PatchExpense,
                PendingMutationStatus.Done, fake.binding),
            observedExpenseCommand(22L, fake.baseExpense, PendingMutationType.ConfirmExpense,
                PendingMutationStatus.Conflict, fake.binding),
        ))
        advanceUntilIdle()
        assertEquals(UiText.res(R.string.expense_command_needs_attention), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertEquals(listOf(21L, 22L), vm.uiState.value.commandRowIds)
        assertEquals("pending", vm.uiState.value.expense?.status)
        assertFalse(vm.uiState.value.commandsCompleted)
        assertFalse(vm.consumeDone())
    }

    @Test
    fun saveSplitsRefusesWhenDraftsNeverLoaded() = edit { fake ->
        // ADR-0042 P1 data-loss guard: an editor whose member roster never
        // arrived has empty splitDrafts; saving would send splits=[] and the
        // backend replace would delete every existing split.
        val vm = viewModel(fake)
        vm._uiState.update { it.copy(splitEditorOpen = true, splitDrafts = emptyList()) }

        vm.saveSplits()
        advanceUntilIdle()

        assertEquals(0, fake.replaceSplitsCalls)
        assertNotNull(vm.uiState.value.splitsMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.splitsMessageTone)
        assertTrue(vm.uiState.value.splitEditorOpen)
    }

    @Test
    fun readOnlyRoleBlocksSaveLoudly() = edit { fake ->
        val vm = viewModel(fake)
        fake.canModifyLedgerFlag = false

        vm.save(draft(merchant = "x"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.readOnly)
        assertNotNull(state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
        assertEquals(0, fake.saveCalls)
    }

    @Test
    fun evenSplitDistributesOnlyTheRemainderAfterDisabledShares() = edit { fake ->
        val vm = viewModel(fake)
        // parent 10.00, a disabled member holds a fixed 3.00 → the two active
        // checked members split the remaining 7.00 as 3.50 each.
        vm._uiState.update {
            it.copy(
                expenseSplits = fake.splits(parentAmountCents = 1000L),
                splitDrafts = listOf(
                    EditableSplit(memberId = 1L, displayName = "禁用", included = true, amountText = "3.00", disabled = true),
                    EditableSplit(memberId = 2L, displayName = "甲", included = true),
                    EditableSplit(memberId = 3L, displayName = "乙", included = true),
                ),
            )
        }

        vm.evenSplitAmounts()

        val drafts = vm.uiState.value.splitDrafts
        assertEquals("3.00", drafts[0].amountText)
        assertEquals("3.50", drafts[1].amountText)
        assertEquals("3.50", drafts[2].amountText)
    }

    @Test
    fun saveItemsSyncedUsesResponseParentToken() = edit { fake ->
        val vm = viewModel(fake)
        vm.openItemsEditor()
        fake.replaceItemsResponder = { _, _, _ ->
            Result.success(ReplaceItemsOutcome.Synced(fake.items(parentRowVersion = 9L)))
        }

        vm.saveItems()
        advanceUntilIdle()

        // The items response already carries the bumped parent token, so same-page
        // follow-up mutations do not depend on a second GET.
        assertEquals(9L, vm.uiState.value.expense?.rowVersion)
        assertFalse(vm.uiState.value.itemEditorOpen)
        assertNotNull(vm.uiState.value.message)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
    }

    @Test
    fun saveSplitsSyncedUsesResponseParentToken() = edit { fake ->
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                splitEditorOpen = true,
                splitDrafts = listOf(EditableSplit(memberId = 1L, displayName = "甲", included = true, amountText = "4.00")),
            )
        }
        fake.replaceSplitsResponder = { _, _, _ ->
            Result.success(ReplaceSplitsOutcome.Synced(fake.splits(parentRowVersion = 10L)))
        }

        vm.saveSplits()
        advanceUntilIdle()

        assertEquals(10L, vm.uiState.value.expense?.rowVersion)
        assertFalse(vm.uiState.value.splitEditorOpen)
        assertNotNull(vm.uiState.value.message)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
    }

    @Test
    fun saveItemsRefusesUnparsableAmountInsteadOfZero() = edit { fake ->
        // Audit P3 #11: "1.2.3" used to silently become a ¥0 item via
        // `parseAmountCents(...) ?: 0L`. The save must refuse loudly and keep
        // the editor open; the repository must never be reached.
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                itemEditorOpen = true,
                expenseItems = fake.items(),
                itemDrafts = listOf(EditableItem(name = "可乐", amountText = "1.2.3")),
            )
        }
        fake.replaceItemsResponder = { _, _, _ -> error("save must not reach the repository") }

        vm.saveItems()
        advanceUntilIdle()

        assertEquals(0, fake.replaceItemsCalls)
        assertNotNull(vm.uiState.value.itemsMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.itemsMessageTone)
        assertTrue(vm.uiState.value.itemEditorOpen)
    }

    @Test
    fun saveItemsBlockedWhenExpenseCurrencyUnsupported() = edit { fake ->
        // PR#255 R10④：record 币种在支持集外（新版服务端币种）→ 禁金额承载编辑 ——
        // fromStorageKey 枚举回落会按 CNY 预填/解析放大 100×；repository 不可达。
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                expense = it.expense?.copy(homeCurrencyCode = "XXX"),
                itemEditorOpen = true,
                expenseItems = fake.items(),
                itemDrafts = listOf(EditableItem(name = "可乐", amountText = "12")),
            )
        }
        fake.replaceItemsResponder = { _, _, _ -> error("save must not reach the repository") }

        vm.saveItems()
        advanceUntilIdle()

        assertEquals(0, fake.replaceItemsCalls)
        assertNotNull(vm.uiState.value.itemsMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.itemsMessageTone)
        assertTrue(vm.uiState.value.itemEditorOpen)
    }

    @Test
    fun saveSplitsBlockedWhenExpenseCurrencyUnsupported() = edit { fake ->
        // R10④ 同伴路径（splits 编辑器）。
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                expense = it.expense?.copy(homeCurrencyCode = "XXX"),
                splitEditorOpen = true,
                splitMembersLoading = false,
                splitDrafts = listOf(EditableSplit(memberId = 1L, displayName = "甲", included = true, amountText = "4.00")),
            )
        }
        fake.replaceSplitsResponder = { _, _, _ -> error("save must not reach the repository") }

        vm.saveSplits()
        advanceUntilIdle()

        assertEquals(0, fake.replaceSplitsCalls)
        assertNotNull(vm.uiState.value.splitsMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.splitsMessageTone)
        assertTrue(vm.uiState.value.splitEditorOpen)
    }

    @Test
    fun saveSplitsRefusesUnparsableAmountInsteadOfZero() = edit { fake ->
        val vm = viewModel(fake)
        vm._uiState.update {
            it.copy(
                splitEditorOpen = true,
                splitDrafts = listOf(
                    EditableSplit(memberId = 1L, displayName = "甲", included = true, amountText = "3.00"),
                    EditableSplit(memberId = 2L, displayName = "乙", included = true, amountText = "1.2.3"),
                ),
            )
        }

        vm.saveSplits()
        advanceUntilIdle()

        assertEquals(0, fake.replaceSplitsCalls)
        assertNotNull(vm.uiState.value.splitsMessage)
        assertEquals(MessageTone.Danger, vm.uiState.value.splitsMessageTone)
        assertTrue(vm.uiState.value.splitEditorOpen)
    }

    @Test
    fun acknowledgeMismatchQueuedKeepsTokenAndShowsOptimisticItems() = edit { fake ->
        val vm = viewModel(fake)
        val tokenBefore = vm.uiState.value.expense
        val optimistic = fake.items()
        fake.ackResponder = { _, _ -> Result.success(ItemsAckOutcome.Queued(optimistic)) }

        vm.acknowledgeItemsMismatch()
        advanceUntilIdle()

        // Offline queue: no fetchExpense — the current token stays.
        assertEquals(tokenBefore, vm.uiState.value.expense)
        assertEquals(optimistic, vm.uiState.value.expenseItems)
        assertNull(vm.uiState.value.itemsMessage)
        assertNotNull(vm.uiState.value.message)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

}

internal class FakeExpenseEditActions : ExpenseEditActions {
    var canModifyLedgerFlag: Boolean = true

    val baseExpense: Expense = Expense(
        id = 7L,
        publicId = "pub-7",
        amountCents = 1000L,
        originalCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1000L,
        merchant = "Merchant",
        category = "其他",
        note = null,
        source = "manual",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "pending",
        expenseTime = null,
        createdAt = "2025-01-01T00:00:00Z",
        updatedAt = "2025-01-01T00:00:00Z",
        rowVersion = 1L,
        confirmedAt = null,
        rejectedAt = null,
    )

    fun items(expenseId: Long = 7L, parentRowVersion: Long = 1L): ExpenseItems = ExpenseItems(
        expenseId = expenseId,
        parentAmountCents = 1000L,
        itemsTotalAmountCents = null,
        mismatchCents = null,
        items = emptyList(),
        parentRowVersion = parentRowVersion,
    )

    fun splits(parentAmountCents: Long? = 1000L, parentRowVersion: Long = 1L): ExpenseSplits = ExpenseSplits(
        expenseId = 7L,
        parentAmountCents = parentAmountCents,
        splitsTotalAmountCents = null,
        mismatchCents = null,
        splits = emptyList<ExpenseSplit>(),
        parentRowVersion = parentRowVersion,
    )

    var fetchExpenseResponder: (suspend (Long) -> Result<Expense>)? = null
    // issue #65 slice 5: the negative-id (offline-create) local-cache load path.
    var localCacheResponder: (suspend (Long) -> Result<Expense>)? = null
    var fetchItemsResponder: (suspend (Long) -> Result<ExpenseItems>)? = null
    var fetchSplitsResponder: (suspend (Long) -> Result<ExpenseSplits>)? = null
    var saveOfflineResponder: (suspend (Long, ExpenseDraft, Expense) -> Result<ExpenseCommandAcceptance>)? = null
    var saveAndConfirmResponder: (suspend (LogicalSessionBinding, Expense, ExpenseDraft) -> Result<ExpenseCommandAcceptance>)? = null
    var ackResponder: (suspend (Expense, ExpenseItems) -> Result<ItemsAckOutcome>)? = null
    var replaceItemsResponder: (suspend (Expense, List<ExpenseItemDraft>, ExpenseItems) -> Result<ReplaceItemsOutcome>)? = null
    var replaceSplitsResponder: (suspend (Expense, List<ExpenseSplitDraft>, ExpenseSplits) -> Result<ReplaceSplitsOutcome>)? = null

    var saveCalls: Int = 0
        private set
    var confirmCalls: Int = 0
        private set
    var categoriesCalls: Int = 0
        private set
    var fetchThumbnailCalls: Int = 0
        private set
    var replaceItemsCalls: Int = 0
        private set
    var replaceSplitsCalls: Int = 0
        private set
    var saveAndConfirmCalls: Int = 0
        private set
    val submittedBindings = mutableListOf<LogicalSessionBinding>()
    var localCacheCalls: Int = 0
        private set
    var fetchItemsCalls: Int = 0
        private set
    var fetchSplitsCalls: Int = 0
        private set

    var fxTaskResult: Result<com.ticketbox.domain.model.BackgroundTask?> = Result.success(null)
    var fxRetryCalls = 0
    var fxReviewCalls = 0
    val binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding")
    val commands = MutableStateFlow(ExpenseCommandObservation(LedgerAccessContext(binding, true), emptyList()))
    override fun captureDeferredLedgerBinding() = binding
    override fun observeExpenseCommands() = commands
    override suspend fun fetchExpenseFx(binding: com.ticketbox.data.repository.LogicalSessionBinding, id: Long) = fxTaskResult
    override suspend fun retryExpenseFx(binding: com.ticketbox.data.repository.LogicalSessionBinding, expense: Expense): Result<com.ticketbox.domain.model.BackgroundTask> {
        fxRetryCalls += 1
        return fxTaskResult.map { requireNotNull(it) }
    }
    override suspend fun fetchExpenseForFxReview(binding: com.ticketbox.data.repository.LogicalSessionBinding, id: Long): Result<Expense> {
        fxReviewCalls += 1
        return fetchExpense(id)
    }
    override fun canModifyLedger(): Boolean = canModifyLedgerFlag

    override suspend fun fetchExpense(id: Long): Result<Expense> =
        fetchExpenseResponder?.invoke(id) ?: Result.success(baseExpense)

    override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> {
        localCacheCalls += 1
        return localCacheResponder?.invoke(id) ?: Result.success(baseExpense)
    }

    override suspend fun categories(): Result<List<String>> {
        categoriesCalls += 1
        return Result.success(listOf("餐饮", "交通"))
    }

    // Succeed by default: the thumbnail FAILURE path logs via android.util.Log,
    // which is not mocked on the unit-test JVM and would crash init.
    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> {
        fetchThumbnailCalls += 1
        return Result.success(
            ProtectedImage(bytes = "thumb".encodeToByteArray(), contentType = "image/jpeg"),
        )
    }

    override suspend fun fetchImage(id: Long): Result<ProtectedImage> =
        Result.success(ProtectedImage(bytes = "full".encodeToByteArray(), contentType = "image/jpeg"))

    override suspend fun saveExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, id: Long, draft: ExpenseDraft, baseline: Expense,
    ): Result<ExpenseCommandAcceptance> {
        saveCalls += 1
        submittedBindings += expectedBinding
        return saveOfflineResponder?.invoke(id, draft, baseline)
            ?: error("saveOfflineResponder not set; got id=$id")
    }

    override suspend fun saveAndConfirmExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense, draft: ExpenseDraft,
    ): Result<ExpenseCommandAcceptance> {
        saveAndConfirmCalls += 1
        submittedBindings += expectedBinding
        return saveAndConfirmResponder?.invoke(expectedBinding, expense, draft)
            ?: error("saveAndConfirmResponder not set")
    }

    override suspend fun confirmExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> {
        confirmCalls += 1
        error("editor confirmation must use atomic saveAndConfirmExpense")
    }

    override suspend fun rejectExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = error("reject not exercised in these tests")

    override suspend fun retryOcrAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = error("retryOcr not exercised in these tests")

    override suspend fun recognizeTextAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense, rawText: String,
    ): Result<ExpenseCommandAcceptance> = error("recognizeText not exercised in these tests")

    override suspend fun markNotDuplicateAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = error("markNotDuplicate not exercised in these tests")

    override suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> {
        fetchItemsCalls += 1
        return fetchItemsResponder?.invoke(id) ?: Result.success(items(id))
    }

    override suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome> =
        ackResponder?.invoke(expense, currentItems) ?: error("ackResponder not set")

    override suspend fun replaceExpenseItemsAllowingOffline(
        expense: Expense,
        items: List<ExpenseItemDraft>,
        currentItems: ExpenseItems,
    ): Result<ReplaceItemsOutcome> {
        replaceItemsCalls += 1
        return replaceItemsResponder?.invoke(expense, items, currentItems)
            ?: error("replaceItemsResponder not set")
    }

    override suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> {
        fetchSplitsCalls += 1
        return fetchSplitsResponder?.invoke(id) ?: Result.success(splits())
    }

    override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> = Result.success(emptyList())

    override suspend fun replaceExpenseSplitsAllowingOffline(
        expense: Expense,
        splits: List<ExpenseSplitDraft>,
        currentSplits: ExpenseSplits,
    ): Result<ReplaceSplitsOutcome> {
        replaceSplitsCalls += 1
        return replaceSplitsResponder?.invoke(expense, splits, currentSplits)
            ?: error("replaceSplitsResponder not set")
    }

}
