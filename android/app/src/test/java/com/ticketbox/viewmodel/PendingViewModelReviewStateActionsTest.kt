package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.R
import com.ticketbox.domain.model.FxContract
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
        val suspected = expense(
            id = 13L,
            amountCents = 100L,
            merchant = "M3",
            details = PendingExpenseDetails(duplicateStatus = "suspected"),
        )
        val missingCategory = expense(id = 14L, amountCents = 100L, merchant = "M4", category = "")
        val fake = FakeReviewActions(
            pending = listOf(ready, missingAmount, missingMerchant, suspected, missingCategory),
        )
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(listOf(10L), fake.confirmedIds)
        assertEquals(1, fake.confirmBatchCalls)
        assertEquals(0, vm.uiState.value.bulkConfirm.succeeded)
        assertTrue(vm.uiState.value.items.any { it.id == ready.id })
        fake.pending = fake.pending.filterNot { it.id == ready.id }
        fake.publishCommand(ready.id, PendingMutationType.ConfirmExpense, PendingMutationStatus.Done)
        advanceUntilIdle()
        val state = vm.uiState.value
        assertEquals(1, state.bulkConfirm.succeeded)
        assertEquals(0, state.bulkConfirm.failed)
        assertFalse(state.bulkConfirm.running)
        assertEquals(setOf(11L, 12L, 13L, 14L), state.items.map { it.id }.toSet())
    }

    @Test
    fun confirmReadyExpensesUsesTheReadyToConfirmFilterCaliber() = review {
        // Same predicate as the ReadyToConfirm inbox filter (PR #230 round 6):
        // fx-pending (server 409s), merchant-noise and raw-blank-category rows
        // must NOT be offered to bulk confirm even though they look complete.
        val ready = expense(id = 10L, amountCents = 100L, merchant = "星巴克")
        val fxPending = expense(id = 15L, amountCents = 100L, merchant = "麦当劳")
            .copy(fxStatus = FxContract.StatusPending)
        val noiseMerchant = expense(id = 16L, amountCents = 100L, merchant = "12:34")
        val rawBlankCategory = expense(id = 17L, amountCents = 100L, merchant = "肯德基", category = "其他")
            .copy(serverCategory = "")
        val fake = FakeReviewActions(
            pending = listOf(ready, fxPending, noiseMerchant, rawBlankCategory),
        )
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(listOf(10L), fake.confirmedIds)
        assertEquals(1, fake.confirmBatchCalls)
        assertEquals(0, vm.uiState.value.bulkConfirm.succeeded)
        assertTrue(vm.uiState.value.items.any { it.id == ready.id })
        fake.pending = fake.pending.filterNot { it.id == ready.id }
        fake.publishCommand(ready.id, PendingMutationType.ConfirmExpense, PendingMutationStatus.Done)
        advanceUntilIdle()
        val state = vm.uiState.value
        assertEquals(1, state.bulkConfirm.succeeded)
        assertEquals(0, state.bulkConfirm.failed)
        assertEquals(setOf(15L, 16L, 17L), state.items.map { it.id }.toSet())
    }

    @Test
    fun confirmReadyExpensesReportsPartialFailure() = review {
        // Usable merchants (multi-char with a letter) so both rows are ready
        // under the shared ReadyToConfirm caliber.
        val a = expense(id = 20L, amountCents = 100L, merchant = "星巴克")
        val b = expense(id = 21L, amountCents = 100L, merchant = "麦当劳")
        val fake = FakeReviewActions(pending = listOf(a, b))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(0, vm.uiState.value.bulkConfirm.succeeded)
        assertEquals(listOf(a, b), vm.uiState.value.items)
        fake.pending = listOf(b)
        fake.publishCommand(a.id, PendingMutationType.ConfirmExpense, PendingMutationStatus.Done)
        fake.publishCommand(b.id, PendingMutationType.ConfirmExpense, PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val state = vm.uiState.value
        assertEquals(1, state.bulkConfirm.succeeded)
        assertEquals(1, state.bulkConfirm.failed)
        assertEquals(UiText.res(R.string.expense_command_needs_attention), state.message)
        assertEquals(listOf(21L), state.items.map { it.id })
    }

    @Test
    fun confirmReadyExpensesShowsHintWhenNoneReady() = review {
        val onlyDup = expense(
            id = 30L,
            amountCents = 100L,
            merchant = "M",
            details = PendingExpenseDetails(duplicateStatus = "suspected"),
        )
        val fake = FakeReviewActions(pending = listOf(onlyDup))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.confirmReadyExpenses()
        advanceUntilIdle()

        assertEquals(0, fake.confirmCalls)
        assertEquals(UiText.res(R.string.pending_review_bulk_none_ready), vm.uiState.value.message)
    }

    @Test
    fun markNotDuplicateClearsSuspectedAndKeepsItem() = review {
        val target = expense(id = 40L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.openDuplicateAction(target)
        vm.markNotDuplicate(target)
        advanceUntilIdle()

        assertEquals("suspected", vm.uiState.value.items.single().duplicateStatus)
        fake.pending = listOf(target.copy(duplicateStatus = "none", rowVersion = 2L))
        fake.publishCommand(target.id, PendingMutationType.MarkNotDuplicate, PendingMutationStatus.Done)
        advanceUntilIdle()
        val state = vm.uiState.value
        assertEquals("none", state.items.single().duplicateStatus)
        assertEquals(UiText.res(R.string.expense_command_completed), state.message)
    }

    @Test
    fun queuedMarkNotDuplicateKeepsOriginalBadgeUntilCompletion() = review {
        val target = expense(id = 52L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openDuplicateAction(target)
        vm.markNotDuplicate(target)
        advanceUntilIdle()
        assertEquals("suspected", vm.uiState.value.items.single().duplicateStatus)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertEquals(1, fake.markNotDuplicateCalls)
        assertEquals(PendingMutationStatus.Pending, fake.commands.value.single().row.status)
    }

    @Test
    fun rejectionOnlyRemovesTheBillAfterItsOriginalCompletion() = review {
        val target = expense(id = 41L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openDuplicateAction(target)
        vm.reject(target)
        advanceUntilIdle()
        assertEquals(listOf(target), vm.uiState.value.items)
        fake.pending = emptyList()
        fake.publishCommand(target.id, PendingMutationType.RejectExpense, PendingMutationStatus.Done,
            target.copy(status = "rejected", rowVersion = 2L, rejectedAt = "2026-09-13T00:01:00Z"))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.items.isEmpty())
        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals(UiText.res(R.string.expense_command_completed), vm.uiState.value.message)
    }

    @Test
    fun queuedConfirmRetainsPendingBillAndOriginalCommand() = review {
        val target = expense(id = 50L, amountCents = 100L, merchant = "M")
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.confirm(target)
        advanceUntilIdle()
        assertEquals(listOf(target), vm.uiState.value.items)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertEquals(1, fake.confirmCalls)
        assertEquals(PendingMutationStatus.Pending, fake.commands.value.single().row.status)
    }

    @Test
    fun queuedRejectRetainsPendingBillWithoutInventingAnUndoReceipt() = review {
        val target = expense(id = 51L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openDuplicateAction(target)
        vm.reject(target)
        advanceUntilIdle()
        assertEquals(listOf(target), vm.uiState.value.items)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertEquals(1, fake.rejectCalls)
        assertEquals(null, vm.uiState.value.undoableExpense)
        assertEquals(PendingMutationStatus.Pending, fake.commands.value.single().row.status)
    }
}
