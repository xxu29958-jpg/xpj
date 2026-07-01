package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * v0.4-alpha4 M1：PendingViewModel 状态流转 review action 单元测试。
 *
 * 覆盖批量确认（confirmReadyExpenses）、重复处理（markNotDuplicate）、
 * 单条确认 / 拒绝以及它们的离线（Queued）出口契约。ADR-0038 撤销 banner
 * 相关的更细分支拆到 [PendingViewModelReviewUndoBannerTest]。
 *
 * 共享脚手架（review 计时器卫生 helper、expense / image 样本构造器、
 * FakeReviewActions）见 [PendingViewModelReviewTestBase] /
 * [FakeReviewActions]。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewStateActionsTest : PendingViewModelReviewTestBase() {

    @Test
    fun confirmReadyExpensesSkipsIncompleteItemsAndDuplicates() = review {
        val ready = expense(id = 10L, amountCents = 100L, merchant = "M1")
        val missingAmount = expense(id = 11L, amountCents = null, merchant = "M2")
        val missingMerchant = expense(id = 12L, amountCents = 100L, merchant = null)
        val suspected = expense(id = 13L, amountCents = 100L, merchant = "M3", duplicateStatus = "suspected")
        val missingCategory = expense(id = 14L, amountCents = 100L, merchant = "M4", category = "")
        val fake = FakeReviewActions(
            pending = listOf(ready, missingAmount, missingMerchant, suspected, missingCategory),
        )
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
        assertEquals(setOf(11L, 12L, 13L, 14L), state.items.map { it.id }.toSet())
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
        assertEquals(UiText.res(R.string.pending_review_bulk_partial, 1, 1), state.message)
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
        assertEquals(UiText.res(R.string.pending_review_bulk_none_ready), vm.uiState.value.message)
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
        assertEquals(UiText.res(R.string.pending_msg_kept), state.message)
    }

    @Test
    fun markNotDuplicateQueuedOfflineKeepsItemWithOfflineMessage() = review {
        // PR-2g.8: offline mark-not-duplicate. The item STAYS in the
        // pending list (unlike confirm/reject) with the badge cleared,
        // and the user sees the "联网后同步" hint.
        val target = expense(id = 52L, duplicateStatus = "suspected")
        val fake = FakeReviewActions(pending = listOf(target))
        fake.markNotDuplicateOfflineResponder = {
            Result.success(
                com.ticketbox.data.repository.ExpenseStateOutcome.Queued(target.copy(duplicateStatus = "none")),
            )
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.markNotDuplicate(target)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("none", state.items.single().duplicateStatus, "queued mark-not-dup keeps the item")
        assertEquals(PendingSheet.None, state.activeSheet)
        assertEquals(UiText.res(R.string.pending_msg_kept_offline), state.message)
        assertEquals(1, fake.markNotDuplicateCalls)
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
        assertEquals(UiText.res(R.string.pending_msg_rejected), vm.uiState.value.message)
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
        assertEquals(UiText.res(R.string.pending_msg_confirmed_offline), vm.uiState.value.message)
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
        assertEquals(UiText.res(R.string.pending_msg_rejected_offline), vm.uiState.value.message)
        assertEquals(1, fake.rejectCalls)
    }
}
