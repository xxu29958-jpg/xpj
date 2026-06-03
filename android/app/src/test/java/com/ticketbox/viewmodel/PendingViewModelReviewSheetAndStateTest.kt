package com.ticketbox.viewmodel

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * v0.4-alpha4 M1：PendingViewModel 只读 / sheet / reducer / ledger-change
 * 单元测试。
 *
 * 覆盖 viewer 只读短路、sheet 开关、reconcileActiveSheet 与
 * PendingUiStateReducer 纯函数契约，以及切换活动账本后丢弃陈旧 pending /
 * thumbnail 响应、上传截图被账本切换打断等边界。
 *
 * 共享脚手架（review 计时器卫生 helper、expense / image 样本构造器、
 * FakeReviewActions）见 [PendingViewModelReviewTestBase] /
 * [FakeReviewActions]。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewSheetAndStateTest : PendingViewModelReviewTestBase() {

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
}
