package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseEditActions
import com.ticketbox.data.repository.ExpenseStateOutcome
import com.ticketbox.data.repository.ItemsAckOutcome
import com.ticketbox.data.repository.ReplaceItemsOutcome
import com.ticketbox.data.repository.ReplaceSplitsOutcome
import com.ticketbox.data.repository.SaveOutcome
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
 * save / confirm 的 Synced·Queued·failure 分支、confirm 的金额守卫与
 * token 级联、saveSplits 的 ADR-0042 P1 防数据丢失守卫、只读门、
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

    private fun draft(amountCents: Long? = null, merchant: String? = null): ExpenseDraft = ExpenseDraft(
        amountCents = amountCents,
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
    fun saveSyncedShowsSuccessAndSignalsDone() = edit { fake ->
        val vm = viewModel(fake)
        val saved = fake.baseExpense.copy(merchant = "新商家", rowVersion = 2L)
        fake.saveOfflineResponder = { _, _, _ -> Result.success(SaveOutcome.Synced(saved)) }

        vm.save(draft(merchant = "新商家"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(saved, state.expense)
        assertFalse(state.saving)
        assertNotNull(state.message)
        assertEquals(MessageTone.Success, state.messageTone)
        assertTrue(vm.consumeDone())
    }

    @Test
    fun saveQueuedSurfacesOfflineHint() = edit { fake ->
        val vm = viewModel(fake)
        val queued = fake.baseExpense.copy(merchant = "离线商家")
        fake.saveOfflineResponder = { _, _, _ -> Result.success(SaveOutcome.Queued(queued)) }

        vm.save(draft(merchant = "离线商家"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(queued, state.expense)
        assertNotNull(state.message)
        assertEquals(MessageTone.Info, state.messageTone)
        assertTrue(vm.consumeDone())
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
    fun confirmChainsSaveThenConfirmWithTheFreshToken() = edit { fake ->
        val vm = viewModel(fake)
        val saved = fake.baseExpense.copy(rowVersion = 5L)
        val confirmed = saved.copy(status = "confirmed")
        fake.saveOfflineResponder = { _, _, _ -> Result.success(SaveOutcome.Synced(saved)) }
        fake.confirmOfflineResponder = { Result.success(ExpenseStateOutcome.Synced(confirmed)) }

        vm.confirm(draft(amountCents = 1200L))
        advanceUntilIdle()

        assertEquals(1, fake.saveCalls)
        assertEquals(1, fake.confirmCalls)
        // The chained confirm must run against the post-save expense (fresh
        // OCC token), not the stale pre-save baseline.
        assertEquals(saved, fake.confirmedExpense)
        assertEquals(confirmed, vm.uiState.value.expense)
        assertTrue(vm.consumeDone())
    }

    @Test
    fun confirmSurfacesConfirmStepFailure() = edit { fake ->
        val vm = viewModel(fake)
        val saved = fake.baseExpense.copy(rowVersion = 5L)
        fake.saveOfflineResponder = { _, _, _ ->
            Result.success(SaveOutcome.Synced(saved))
        }
        fake.confirmOfflineResponder = { Result.failure(RuntimeException("conflict")) }

        vm.confirm(draft(amountCents = 500L))
        advanceUntilIdle()

        assertNotNull(vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertFalse(vm.uiState.value.saving)
        assertFalse(vm.consumeDone())
        // The save step COMMITTED (server bumped the OCC token). The failed
        // confirm must write the post-save expense back into state — leaving
        // the stale pre-save baseline would 409 every later mutate on this page.
        assertEquals(saved, vm.uiState.value.expense)
    }

    @Test
    fun confirmQueuedBehindOfflineSaveSurfacesOfflineHint() = edit { fake ->
        // Per-target FIFO (codex review P1): when the save queued its PATCH,
        // the repository diverts the chained confirm to the queue too. The VM
        // must surface the offline hint (mirrors reject/save) instead of
        // silently navigating away as if the confirm hit the server.
        val vm = viewModel(fake)
        val queued = fake.baseExpense.copy(merchant = "离线商家")
        fake.saveOfflineResponder = { _, _, _ -> Result.success(SaveOutcome.Queued(queued)) }
        fake.confirmOfflineResponder = { expense ->
            Result.success(ExpenseStateOutcome.Queued(expense.copy(status = "confirmed")))
        }

        vm.confirm(draft(amountCents = 1200L))
        advanceUntilIdle()

        assertEquals(
            UiText.res(R.string.expense_edit_confirm_offline_queued),
            vm.uiState.value.message,
        )
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
        assertEquals("confirmed", vm.uiState.value.expense?.status)
        assertTrue(vm.consumeDone())
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
    var saveOfflineResponder: (suspend (Long, ExpenseDraft, Expense) -> Result<SaveOutcome>)? = null
    var confirmOfflineResponder: (suspend (Expense) -> Result<ExpenseStateOutcome>)? = null
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
    var confirmedExpense: Expense? = null
        private set
    var localCacheCalls: Int = 0
        private set
    var fetchItemsCalls: Int = 0
        private set
    var fetchSplitsCalls: Int = 0
        private set

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

    override suspend fun updateExpense(id: Long, draft: ExpenseDraft, baseline: Expense?): Result<Expense> =
        Result.failure(IllegalStateException("direct updateExpense not exercised"))

    override suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<SaveOutcome> {
        saveCalls += 1
        return saveOfflineResponder?.invoke(id, draft, baseline)
            ?: error("saveOfflineResponder not set; got id=$id")
    }

    override suspend fun confirmExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> {
        confirmCalls += 1
        confirmedExpense = expense
        return confirmOfflineResponder?.invoke(expense)
            ?: error("confirmOfflineResponder not set")
    }

    override suspend fun rejectExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        error("rejectOfflineResponder not exercised in these tests")

    override suspend fun retryOcrAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        error("retryOcr not exercised in these tests")

    override suspend fun recognizeTextAllowingOffline(expense: Expense, rawText: String): Result<ExpenseStateOutcome> =
        error("recognizeText not exercised in these tests")

    override suspend fun markNotDuplicateAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        error("markNotDuplicate not exercised in these tests")

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
