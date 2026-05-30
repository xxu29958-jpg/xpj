package com.ticketbox.viewmodel

import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * v0.4-alpha4 M1：PendingViewModel Review Actions 单元测试。
 *
 * 通过 [PendingReviewActions] 接口注入 FakeReviewActions，
 * 验证 QuickCategory / QuickMerchant / MissingAmount /
 * BulkConfirm / DuplicateAction 五条 review action 的核心契约。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PendingViewModelReviewActionsTest {

    private fun review(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun saveQuickCategorySendsTrimmedDraftAndUpdatesItem() = review {
        val target = expense(id = 1L, category = "未分类")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { id, draft ->
            assertEquals(1L, id)
            assertEquals("交通", draft.category)
            assertNull(draft.amountCents)
            assertNull(draft.merchant)
            Result.success(target.copy(category = "交通"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickCategory(target.id, "  交通  ")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("交通", state.items.single().category)
        assertEquals(PendingSheet.None, state.activeSheet)
        assertEquals("已更新分类", state.message)
        assertTrue(state.actionInProgressIds.isEmpty())
        assertEquals(1, fake.updateCalls)
    }

    @Test
    fun saveQuickCategoryShowsErrorOnFailure() = review {
        val target = expense(id = 2L, category = "未分类")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, _ -> Result.failure(RuntimeException("网络忙")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickCategory(target.id, "餐饮")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("未分类", state.items.single().category)
        assertEquals("网络忙", state.message)
        assertTrue(state.actionInProgressIds.isEmpty())
    }

    @Test
    fun saveQuickMerchantRejectsBlankAndDoesNotCallRepository() = review {
        val target = expense(id = 3L, merchant = null)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickMerchant(target.id, "   ")
        advanceUntilIdle()

        assertEquals(0, fake.updateCalls)
        assertEquals("请输入商家名称。", vm.uiState.value.message)
    }

    @Test
    fun saveQuickMerchantSubmitsTrimmedValue() = review {
        val target = expense(id = 4L, merchant = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals("星巴克", draft.merchant)
            Result.success(target.copy(merchant = "星巴克"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveQuickMerchant(target.id, "  星巴克 ")
        advanceUntilIdle()

        assertEquals("星巴克", vm.uiState.value.items.single().merchant)
        assertEquals("已更新商家", vm.uiState.value.message)
    }

    @Test
    fun saveAmountDraftRejectsZeroAndNegative() = review {
        val target = expense(id = 5L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 0L)
        advanceUntilIdle()
        assertEquals(0, fake.updateCalls)
        assertEquals("金额必须大于 0。", vm.uiState.value.message)

        vm.saveAmountDraft(target.id, -100L)
        advanceUntilIdle()
        assertEquals(0, fake.updateCalls)
    }

    @Test
    fun saveAmountDraftPatchesWithoutConfirm() = review {
        val target = expense(id = 6L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(CurrencyCode.CNY, draft.originalCurrencyCode)
            assertEquals(1234L, draft.originalAmountMinor)
            Result.success(target.copy(amountCents = 1234L, originalAmountMinor = 1234L))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 1234L)
        advanceUntilIdle()

        assertEquals(1234L, vm.uiState.value.items.single().amountCents)
        assertEquals(0, fake.confirmCalls)
        assertEquals("已保存金额", vm.uiState.value.message)
    }

    @Test
    fun saveAmountDraftPatchesOriginalForeignAmount() = review {
        val target = expense(
            id = 16L,
            amountCents = null,
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = null,
        )
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(CurrencyCode.USD, draft.originalCurrencyCode)
            assertEquals(12345L, draft.originalAmountMinor)
            Result.success(target.copy(originalAmountMinor = 12345L))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountDraft(target.id, 12345L)
        advanceUntilIdle()

        assertEquals(12345L, vm.uiState.value.items.single().originalAmountMinor)
    }

    @Test
    fun saveAmountAndConfirmRunsUpdateThenConfirm() = review {
        val target = expense(id = 7L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, draft ->
            assertEquals(null, draft.amountCents)
            assertEquals(4200L, draft.originalAmountMinor)
            Result.success(target.copy(amountCents = 4200L, originalAmountMinor = 4200L))
        }
        fake.confirmResponder = { Result.success(target.copy(amountCents = 4200L, status = "confirmed")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountAndConfirm(target.id, 4200L)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.items.isEmpty(), "已确认条目应该从 pending 列表中移除")
        assertEquals("已保存并确认入账", state.message)
        assertEquals(1, fake.updateCalls)
        assertEquals(1, fake.confirmCalls)
    }

    @Test
    fun saveAmountAndConfirmKeepsItemWhenUpdateFails() = review {
        val target = expense(id = 8L, amountCents = null)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.updateResponder = { _, _ -> Result.failure(RuntimeException("amount_required")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.saveAmountAndConfirm(target.id, 5000L)
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.items.size)
        assertEquals(0, fake.confirmCalls)
        assertEquals("amount_required", vm.uiState.value.message)
    }

    @Test
    fun confirmReadyExpensesSkipsMissingAmountAndDuplicates() = review {
        val ready = expense(id = 10L, amountCents = 100L, merchant = "M1")
        val missingAmount = expense(id = 11L, amountCents = null, merchant = "M2")
        val missingMerchant = expense(id = 12L, amountCents = 100L, merchant = null)
        val suspected = expense(id = 13L, amountCents = 100L, merchant = "M3", duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(ready, missingAmount, missingMerchant, suspected))
        fake.confirmResponder = { id -> Result.success(ready.copy(id = id, status = "confirmed")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(listOf(10L), fake.confirmedIds)
        val state = vm.uiState.value
        assertEquals(1, state.bulkConfirm.succeeded)
        assertEquals(0, state.bulkConfirm.failed)
        assertFalse(state.bulkConfirm.running)
        assertEquals(setOf(11L, 12L, 13L), state.items.map { it.id }.toSet())
    }

    @Test
    fun confirmReadyExpensesReportsPartialFailure() = review {
        val a = expense(id = 20L, amountCents = 100L, merchant = "A")
        val b = expense(id = 21L, amountCents = 100L, merchant = "B")
        val fake = FakeReviewActions(pending = listOf(a, b))
        fake.confirmResponder = { id ->
            if (id == 21L) Result.failure(RuntimeException("server_error"))
            else Result.success(a.copy(id = id, status = "confirmed"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, state.bulkConfirm.succeeded)
        assertEquals(1, state.bulkConfirm.failed)
        assertEquals("确认完成：成功 1，失败 1", state.message)
        assertEquals(listOf(21L), state.items.map { it.id })
    }

    @Test
    fun confirmReadyExpensesShowsHintWhenNoneReady() = review {
        val onlyDup = expense(id = 30L, amountCents = 100L, merchant = "M", duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(onlyDup))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(0, fake.confirmCalls)
        assertEquals("没有可直接确认的账单。", vm.uiState.value.message)
    }

    @Test
    fun markNotDuplicateClearsSuspectedAndKeepsItem() = review {
        val target = expense(id = 40L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.markNotDuplicateResponder = { Result.success(target.copy(duplicateStatus = "none")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.markNotDuplicate(target)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("none", state.items.single().duplicateStatus)
        assertEquals(PendingSheet.None, state.activeSheet)
        assertEquals("已保留这条账单", state.message)
    }

    @Test
    fun rejectExpenseRemovesItem() = review {
        val target = expense(id = 41L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectResponder = { Result.success(target) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.reject(target)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.items.isEmpty())
        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals("已删除", vm.uiState.value.message)
    }

    @Test
    fun confirmQueuedOfflineRemovesItemWithOfflineMessage() = review {
        // PR-2g.7: offline confirm. The repository returns Queued; the
        // item still leaves the pending list optimistically and the
        // user sees the "联网后同步" hint instead of "已确认入账".
        val target = expense(id = 50L, amountCents = 100L, merchant = "M")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.confirmOfflineResponder = {
            Result.success(
                com.ticketbox.data.repository.ExpenseStateOutcome.Queued(target.copy(status = "confirmed")),
            )
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.confirm(target)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.items.isEmpty(), "queued confirm still removes from pending")
        assertEquals("已离线确认，联网后同步", vm.uiState.value.message)
        assertEquals(1, fake.confirmCalls)
    }

    @Test
    fun rejectQueuedOfflineRemovesItemWithOfflineMessage() = review {
        val target = expense(id = 51L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.rejectOfflineResponder = {
            Result.success(
                com.ticketbox.data.repository.ExpenseStateOutcome.Queued(target.copy(status = "rejected")),
            )
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.reject(target)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.items.isEmpty())
        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals("已离线删除，联网后同步", vm.uiState.value.message)
        assertEquals(1, fake.rejectCalls)
    }

    @Test
    fun viewerWriteActionsShortCircuitWithoutRepositoryCalls() = review {
        val target = expense(id = 42L, amountCents = 100L, merchant = "M")
        val fake = FakeReviewActions(pending = listOf(target), canModifyLedger = false)
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.readOnly)
        assertFalse(vm.markUploadPreparing())
        vm.openQuickCategory(target)
        vm.saveQuickCategory(target.id, "交通")
        vm.confirm(target)
        vm.reject(target)
        vm.markNotDuplicate(target)
        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals(READ_ONLY_LEDGER_MESSAGE, vm.uiState.value.message)
        assertEquals(0, fake.updateCalls)
        assertEquals(0, fake.confirmCalls)
        assertEquals(0, fake.rejectCalls)
        assertEquals(0, fake.markNotDuplicateCalls)
        assertEquals(0, fake.uploadCalls)
    }

    @Test
    fun openAndCloseSheetTogglesActiveSheet() = review {
        val target = expense(id = 50L)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openQuickCategory(target)
        assertEquals(PendingSheet.QuickCategory(target), vm.uiState.value.activeSheet)
        vm.closeSheet()
        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)

        vm.openBulkConfirm()
        assertEquals(PendingSheet.BulkConfirm, vm.uiState.value.activeSheet)
    }

    @Test
    fun reconcileActiveSheetUsesLatestExpenseSnapshot() = review {
        val stale = expense(id = 60L, category = "其他")
        val latest = stale.copy(category = "交通", updatedAt = "2025-01-01T00:01:00Z")

        val reconciled = reconcileActiveSheet(PendingSheet.QuickCategory(stale), listOf(latest))

        assertEquals(PendingSheet.QuickCategory(latest), reconciled)
    }

    @Test
    fun reconcileActiveSheetClosesWhenExpenseLeavesPendingList() = review {
        val stale = expense(id = 61L, amountCents = null)

        val reconciled = reconcileActiveSheet(PendingSheet.MissingAmount(stale), emptyList())

        assertEquals(PendingSheet.None, reconciled)
    }

    @Test
    fun reducerRefreshKeepsOnlyActiveThumbnailsAndUpdatesOpenSheet() = review {
        val stale = expense(id = 70L, category = "其他")
        val latest = stale.copy(category = "交通", updatedAt = "2025-01-01T00:01:00Z")
        val activeImage = image("active")
        val oldImage = image("old")
        val state = PendingUiState(
            items = listOf(stale),
            thumbnails = mapOf(stale.id to activeImage, 99L to oldImage),
            activeSheet = PendingSheet.QuickCategory(stale),
            loading = true,
        )

        val next = PendingUiStateReducer.afterRefresh(state, listOf(latest), readOnly = false)

        assertEquals(listOf(latest), next.items)
        assertTrue(next.thumbnails[latest.id] === activeImage)
        assertFalse(next.thumbnails.containsKey(99L))
        assertEquals(PendingSheet.QuickCategory(latest), next.activeSheet)
        assertFalse(next.loading)
    }

    @Test
    fun reducerConfirmedRemovesItemThumbnailAndProgressFlag() = review {
        val target = expense(id = 71L)
        val other = expense(id = 72L)
        val state = PendingUiState(
            items = listOf(target, other),
            thumbnails = mapOf(target.id to image("target"), other.id to image("other")),
            actionInProgressIds = setOf(target.id, other.id),
            activeSheet = PendingSheet.MissingAmount(target),
        )

        val next = PendingUiStateReducer.afterConfirmed(state, target, message = "已确认入账")

        assertEquals(listOf(other), next.items)
        assertFalse(next.thumbnails.containsKey(target.id))
        assertTrue(next.thumbnails.containsKey(other.id))
        assertEquals(setOf(other.id), next.actionInProgressIds)
        assertEquals(PendingSheet.None, next.activeSheet)
        assertEquals("已确认入账", next.message)
    }

    @Test
    fun reducerRejectedRemovesItemAndClosesSheet() = review {
        val target = expense(id = 73L)
        val state = PendingUiState(
            items = listOf(target),
            thumbnails = mapOf(target.id to image("target")),
            actionInProgressIds = setOf(target.id),
            activeSheet = PendingSheet.Duplicate(target),
        )

        val next = PendingUiStateReducer.afterRejected(state, target, message = "已删除")

        assertTrue(next.items.isEmpty())
        assertTrue(next.thumbnails.isEmpty())
        assertTrue(next.actionInProgressIds.isEmpty())
        assertEquals(PendingSheet.None, next.activeSheet)
        assertEquals("已删除", next.message)
    }

    @Test
    fun reducerUpdatedReplacesItemAndRefreshesOpenSheetSnapshot() = review {
        val stale = expense(id = 74L, merchant = "旧商家")
        val updated = stale.copy(merchant = "新商家", updatedAt = "2025-01-01T00:02:00Z")
        val state = PendingUiState(
            items = listOf(stale),
            actionInProgressIds = setOf(stale.id),
            activeSheet = PendingSheet.QuickMerchant(stale),
        )

        val next = PendingUiStateReducer.afterUpdated(
            current = state,
            updated = updated,
            closeSheet = false,
            message = "已更新商家",
        )

        assertEquals(listOf(updated), next.items)
        assertTrue(next.actionInProgressIds.isEmpty())
        assertEquals(PendingSheet.QuickMerchant(updated), next.activeSheet)
        assertEquals("已更新商家", next.message)
    }

    @Test
    fun activeLedgerChangeDropsStalePendingItemsAndReloads() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(
            pending = listOf(expense(id = 80L, merchant = "Old Ledger")),
            activeLedgerFlow = ledgerFlow,
        )
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertEquals(listOf("Old Ledger"), vm.uiState.value.items.map { it.merchant })

        fake.pending = listOf(expense(id = 81L, merchant = "New Ledger"))
        ledgerFlow.value = "family"
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(listOf("New Ledger"), vm.uiState.value.items.map { it.merchant })
        assertFalse(vm.uiState.value.thumbnails.containsKey(80L))
    }

    @Test
    fun stalePendingResponseAfterLedgerChangeIsIgnored() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val firstResponse = CompletableDeferred<Result<List<Expense>>>()
        val secondResponse = CompletableDeferred<Result<List<Expense>>>()
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow)
        var fetchIndex = 0
        fake.fetchPendingResponder = {
            fetchIndex += 1
            if (fetchIndex == 1) firstResponse.await() else secondResponse.await()
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        fake.pending = emptyList()
        ledgerFlow.value = "family"
        advanceUntilIdle()

        firstResponse.complete(Result.success(listOf(expense(id = 90L, merchant = "Old Ledger"))))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.items.isEmpty())

        secondResponse.complete(Result.success(listOf(expense(id = 91L, merchant = "New Ledger"))))
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(listOf("New Ledger"), vm.uiState.value.items.map { it.merchant })
    }

    @Test
    fun staleThumbnailResponseAfterLedgerChangeIsIgnored() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val thumbnailResponse = CompletableDeferred<Result<ProtectedImage>>()
        val fake = FakeReviewActions(
            pending = listOf(expense(id = 92L, merchant = "Old Ledger", imagePath = "uploads/old.jpg")),
            activeLedgerFlow = ledgerFlow,
        )
        fake.thumbnailResponder = { thumbnailResponse.await() }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        fake.pending = emptyList()
        ledgerFlow.value = "family"
        advanceUntilIdle()

        thumbnailResponse.complete(Result.success(image("old-ledger")))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.thumbnails.containsKey(92L))
    }

    @Test
    fun uploadPreparedBeforeLedgerChangeIsDroppedBeforeRepositoryCall() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        ledgerFlow.value = "family"
        advanceUntilIdle()

        vm.uploadScreenshot(
            fileName = "receipt.jpg",
            contentType = "image/jpeg",
            bytes = byteArrayOf(1, 2, 3),
            uploadAlreadyStarted = true,
        )
        advanceUntilIdle()

        assertEquals(0, fake.uploadCalls)
        assertEquals("账本已切换，请重新选择截图上传。", vm.uiState.value.message)
    }

    private fun expense(
        id: Long,
        amountCents: Long? = 100L,
        merchant: String? = "Merchant",
        category: String = "其他",
        duplicateStatus: String = "none",
        status: String = "pending",
        originalCurrencyCode: CurrencyCode = CurrencyCode.CNY,
        originalAmountMinor: Long? = amountCents,
        imagePath: String? = null,
    ): Expense = Expense(
        id = id,
        publicId = "pub-$id",
        amountCents = amountCents,
        originalCurrency = originalCurrencyCode,
        originalCurrencyCode = originalCurrencyCode,
        originalAmountMinor = originalAmountMinor,
        merchant = merchant,
        category = category,
        note = null,
        source = "manual",
        imagePath = imagePath,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = duplicateStatus,
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = status,
        expenseTime = null,
        createdAt = "2025-01-01T00:00:00Z",
        updatedAt = "2025-01-01T00:00:00Z",
        confirmedAt = null,
        rejectedAt = null,
    )

    private fun image(label: String): ProtectedImage =
        ProtectedImage(bytes = label.encodeToByteArray(), contentType = "image/jpeg")
}

private class FakeReviewActions(
    pending: List<Expense> = emptyList(),
    private val categoryOptions: List<String> = listOf("餐饮", "交通", "购物"),
    private val canModifyLedger: Boolean = true,
    private val activeLedgerFlow: Flow<String?> = emptyFlow(),
    private val activeLedgerIdProvider: () -> String? = { null },
) : PendingReviewActions {

    var pending: List<Expense> = pending

    var updateResponder: (suspend (Long, ExpenseDraft) -> Result<Expense>)? = null
    var confirmResponder: (suspend (Long) -> Result<Expense>)? = null
    var rejectResponder: (suspend (Long) -> Result<Expense>)? = null
    var markNotDuplicateResponder: (suspend (Long) -> Result<Expense>)? = null
    // PR-2g.7: offline-aware confirm/reject. Default to wrapping the
    // existing confirm/rejectResponder in a Synced outcome so the
    // online-path tests keep passing unchanged; set these to drive
    // the Queued (offline) branch.
    var confirmOfflineResponder: (suspend (Long) -> Result<com.ticketbox.data.repository.ExpenseStateOutcome>)? = null
    var rejectOfflineResponder: (suspend (Long) -> Result<com.ticketbox.data.repository.ExpenseStateOutcome>)? = null
    var fetchPendingResponder: (suspend () -> Result<List<Expense>>)? = null
    var thumbnailResponder: (suspend (Long) -> Result<ProtectedImage>)? = null

    var updateCalls: Int = 0
        private set
    var confirmCalls: Int = 0
        private set
    var rejectCalls: Int = 0
        private set
    var markNotDuplicateCalls: Int = 0
        private set
    var uploadCalls: Int = 0
        private set
    var fetchPendingCalls: Int = 0
        private set
    val confirmedIds = mutableListOf<Long>()

    override fun canModifyLedger(): Boolean = canModifyLedger

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun currentActiveLedgerId(): String? = activeLedgerIdProvider()

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        fetchPendingResponder?.let { return it() }
        return Result.success(pending)
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        thumbnailResponder?.invoke(id)
            ?: Result.failure(IllegalStateException("no thumbnail in tests"))

    override suspend fun updateExpense(id: Long, draft: ExpenseDraft, baseline: Expense?): Result<Expense> {
        updateCalls += 1
        return updateResponder?.invoke(id, draft)
            ?: error("updateResponder not set; got id=$id draft=$draft baseline=$baseline")
    }

    override suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<com.ticketbox.data.repository.SaveOutcome> =
        Result.failure(IllegalStateException("not exercised — PendingViewModel uses updateExpense"))

    override suspend fun confirmExpense(id: Long, expectedUpdatedAt: String): Result<Expense> {
        confirmCalls += 1
        confirmedIds += id
        return confirmResponder?.invoke(id)
            ?: error("confirmResponder not set; got id=$id token=$expectedUpdatedAt")
    }

    override suspend fun rejectExpense(id: Long, expectedUpdatedAt: String): Result<Expense> {
        rejectCalls += 1
        return rejectResponder?.invoke(id) ?: error("rejectResponder not set")
    }

    override suspend fun confirmExpenseAllowingOffline(
        expense: Expense,
    ): Result<com.ticketbox.data.repository.ExpenseStateOutcome> {
        confirmCalls += 1
        confirmedIds += expense.id
        confirmOfflineResponder?.let { return it(expense.id) }
        return confirmResponder?.invoke(expense.id)
            ?.map { com.ticketbox.data.repository.ExpenseStateOutcome.Synced(it) }
            ?: error("confirmResponder/confirmOfflineResponder not set; got id=${expense.id}")
    }

    override suspend fun rejectExpenseAllowingOffline(
        expense: Expense,
    ): Result<com.ticketbox.data.repository.ExpenseStateOutcome> {
        rejectCalls += 1
        rejectOfflineResponder?.let { return it(expense.id) }
        return rejectResponder?.invoke(expense.id)
            ?.map { com.ticketbox.data.repository.ExpenseStateOutcome.Synced(it) }
            ?: error("rejectResponder/rejectOfflineResponder not set")
    }

    override suspend fun markNotDuplicate(id: Long, expectedUpdatedAt: String): Result<Expense> {
        markNotDuplicateCalls += 1
        return markNotDuplicateResponder?.invoke(id) ?: error("markNotDuplicateResponder not set")
    }

    override suspend fun categories(): Result<List<String>> = Result.success(categoryOptions)

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> {
        uploadCalls += 1
        return Result.failure(IllegalStateException("upload not exercised in tests"))
    }
}
