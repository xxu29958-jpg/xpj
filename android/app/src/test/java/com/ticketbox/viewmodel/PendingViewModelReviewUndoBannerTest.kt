package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Original rejected receipts, explicit Undo admission and independent completion. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelReviewUndoBannerTest : PendingViewModelReviewTestBase() {
    private fun FakeReviewActions.completeRejection(target: Expense): Expense {
        val receipt = target.copy(status = "rejected", rowVersion = target.rowVersion + 1,
            rejectedAt = "2026-09-13T00:01:00Z")
        pending = pending.filterNot { it.id == target.id }
        publishCommand(target.id, PendingMutationType.RejectExpense, PendingMutationStatus.Done, receipt)
        return receipt
    }

    @Test
    fun completedRejectionSeedsTheOriginalReceiptOnlyOnce() = review {
        val target = expense(id = 100L)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(target)
        runCurrent()
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(listOf(target), vm.uiState.value.items)
        val receipt = fake.completeRejection(target)
        runCurrent()
        assertEquals(receipt, vm.uiState.value.undoableExpense)
        assertEquals(UiText.res(R.string.expense_command_completed), vm.uiState.value.message)
        advanceTimeBy(4_000)
        fake.commands.value = fake.commands.value.map { it.copy(row = it.row.copy(retryCount = 1)) }
        runCurrent()
        advanceTimeBy(1_001)
        runCurrent()
        assertNull(vm.uiState.value.undoableExpense, "duplicate observation must not restart the banner timer")
    }

    @Test
    fun queuedRejectionPreservesAnEarlierCompletedBanner() = review {
        val first = expense(id = 200L, merchant = "星巴克", amountCents = 4800L)
        val second = expense(id = 201L, merchant = "便利店", amountCents = 1200L)
        val fake = FakeReviewActions(pending = listOf(first, second))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(first)
        runCurrent()
        val receipt = fake.completeRejection(first)
        runCurrent()
        vm.reject(second)
        runCurrent()
        assertEquals(receipt, vm.uiState.value.undoableExpense)
        assertEquals(listOf(second), vm.uiState.value.items)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
    }

    @Test
    fun undoUsesOriginalRejectedVersionAndRestoresAtTopOnlyAfterCompletion() = review {
        val keep = expense(id = 300L)
        val target = expense(id = 301L)
        val fake = FakeReviewActions(pending = listOf(target, keep))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(target)
        runCurrent()
        val receipt = fake.completeRejection(target)
        runCurrent()
        fake.undoRejectResponder = { binding, original ->
            assertEquals(fake.uploadIntents.currentBinding, binding)
            assertEquals(receipt, original)
            Result.success(Unit)
        }
        vm.undoReject()
        runCurrent()
        assertEquals(listOf(keep), vm.uiState.value.items)
        assertNull(vm.uiState.value.undoableExpense)
        assertTrue(target.id in vm.uiState.value.actionInProgressIds)
        val restored = target.copy(rowVersion = receipt.rowVersion + 1)
        fake.pending = listOf(restored, keep)
        fake.publishCommand(target.id, PendingMutationType.UndoExpense, PendingMutationStatus.Done, restored)
        runCurrent()
        assertEquals(listOf(restored, keep), vm.uiState.value.items)
        assertFalse(target.id in vm.uiState.value.actionInProgressIds)
    }

    @Test
    fun unavailableUndoKeepsTheFailedOriginalVisibleWithoutRestoringTheBill() = review {
        val target = expense(id = 400L)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(target)
        runCurrent()
        fake.completeRejection(target)
        runCurrent()
        vm.undoReject()
        runCurrent()
        val original = fake.commands.value.last().row
        fake.publishCommand(target.id, PendingMutationType.UndoExpense, PendingMutationStatus.Failed,
            error = "expense_not_found")
        runCurrent()
        assertTrue(vm.uiState.value.items.isEmpty())
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(UiText.res(R.string.expense_command_needs_attention), vm.uiState.value.message)
        assertEquals(setOf(original.id), vm.commandRowsByExpense[target.id])
        assertEquals(original.idempotencyKey, fake.commands.value.last().row.idempotencyKey)
    }

    @Test
    fun undoAdmissionFailureRestoresOriginalBannerForRetry() = review {
        val target = expense(id = 500L)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(target)
        runCurrent()
        val receipt = fake.completeRejection(target)
        runCurrent()
        fake.undoRejectResponder = { _, _ -> Result.failure(RepositoryException("无法保存原操作。", errorCode = null)) }
        vm.undoReject()
        runCurrent()
        assertEquals(receipt, vm.uiState.value.undoableExpense)
        assertEquals(UiText.raw("无法保存原操作。"), vm.uiState.value.message)
        assertFalse(target.id in vm.uiState.value.actionInProgressIds)
        assertEquals(1, fake.commands.value.size, "failed admission cannot manufacture an Undo row")
    }

    @Test
    fun ignoredDuplicateLeavesOnlyAfterCompletionAndNeverSeedsUndo() = review {
        val target = expense(id = 600L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openDuplicateAction(target)
        vm.ignoreDuplicate(target)
        runCurrent()
        assertEquals(listOf(target), vm.uiState.value.items)
        assertNull(vm.uiState.value.undoableExpense)
        fake.completeRejection(target)
        runCurrent()
        assertTrue(vm.uiState.value.items.isEmpty())
        assertEquals(PendingSheet.None, vm.uiState.value.activeSheet)
        assertEquals(1, fake.rejectCalls)
        assertFalse(target.id in vm.uiState.value.actionInProgressIds)
        assertNull(vm.uiState.value.undoableExpense)
    }

    @Test
    fun queuedIgnoreDuplicateRetainsTheOriginalBillAndCommand() = review {
        val target = expense(id = 601L, details = PendingExpenseDetails(duplicateStatus = "suspected"))
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openDuplicateAction(target)
        vm.ignoreDuplicate(target)
        runCurrent()
        assertEquals(listOf(target), vm.uiState.value.items)
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
        assertEquals(PendingMutationStatus.Pending, fake.commands.value.single().row.status)
    }

    @Test
    fun confirmDismissesPriorUndoableBannerWhileRemainingUnconfirmed() = review {
        val a = expense(id = 700L)
        val b = expense(id = 701L, amountCents = 100L, merchant = "M")
        val fake = FakeReviewActions(pending = listOf(a, b))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(a)
        runCurrent()
        fake.completeRejection(a)
        runCurrent()
        assertNotNull(vm.uiState.value.undoableExpense)
        vm.confirm(b)
        runCurrent()
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(listOf(b), vm.uiState.value.items)
        assertEquals(UiText.res(R.string.expense_command_accepted), vm.uiState.value.message)
    }

    @Test
    fun viewerDemotionMidBannerClearsUndoableExpense() = review {
        val target = expense(id = 900L)
        val fake = FakeReviewActions(pending = listOf(target))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.reject(target)
        runCurrent()
        fake.completeRejection(target)
        runCurrent()
        assertNotNull(vm.uiState.value.undoableExpense)
        fake.canModifyLedgerFlag = false
        vm.undoReject()
        runCurrent()
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(readOnlyMessage(), vm.uiState.value.message)
    }

    @Test
    fun initialHistoricalCompletionDoesNotInventARejectionBanner() = review {
        val old = expense(id = 950L)
        val current = expense(id = 951L)
        val fake = FakeReviewActions(pending = listOf(current))
        fake.commands.value = listOf(observedExpenseCommand(50L, old, PendingMutationType.RejectExpense,
            PendingMutationStatus.Done, fake.uploadIntents.currentBinding,
            old.copy(status = "rejected", rowVersion = 2, rejectedAt = "2026-09-13T00:01:00Z")))
        var changes = 0
        val vm = pendingViewModel(fake, onDataChanged = { changes++ })
        advanceUntilIdle()
        assertEquals(listOf(current), vm.uiState.value.items)
        assertNull(vm.uiState.value.undoableExpense)
        assertEquals(0, changes)
    }
}
