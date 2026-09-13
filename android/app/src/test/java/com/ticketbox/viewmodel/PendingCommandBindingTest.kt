package com.ticketbox.viewmodel

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals

/** A late admission may retain A's command, but cannot advance B's review. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingCommandBindingTest : PendingViewModelReviewTestBase() {
    @Test
    fun lateQuickEditCannotReplaceAnotherLedgersSameIdOrAdvanceItsSheet() = review {
        val ledger = MutableStateFlow<String?>("ledger-a")
        val a = expense(1L, merchant = null)
        val b = expense(1L, merchant = null).copy(publicId = "ledger-b-1")
        val accepted = CompletableDeferred<Result<Expense>>()
        val fake = FakeReviewActions(listOf(a), activeLedgerFlow = ledger, activeLedgerIdProvider = { ledger.value })
        fake.saveResponder = { binding, baseline, _ ->
            assertEquals("ledger-a", binding.ledgerId)
            assertEquals(a, baseline)
            accepted.await()
        }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openQuickMerchant(a)
        vm.saveQuickMerchant(a.id, "A merchant")
        runCurrent()
        fake.pending = listOf(b, expense(2L, merchant = null))
        ledger.value = "ledger-b"
        runCurrent()
        vm.openQuickMerchant(b)
        val before = vm.uiState.value
        val skipped = vm.reviewSkippedIds.toSet()
        accepted.complete(Result.success(a.copy(merchant = "A merchant")))
        runCurrent()
        assertEquals(before.items, vm.uiState.value.items)
        assertEquals(before.activeSheet, vm.uiState.value.activeSheet)
        assertEquals(before.reviewRemaining, vm.uiState.value.reviewRemaining)
        assertEquals(before.message, vm.uiState.value.message)
        assertEquals(skipped, vm.reviewSkippedIds)
        assertEquals("ledger-a", fake.admissions.single().first.ledgerId)
    }

    @Test
    fun lateSaveAndConfirmCannotSkipAnotherLedgersAmountReview() = review {
        val ledger = MutableStateFlow<String?>("ledger-a")
        val a = expense(1L, amountCents = null)
        val b = a.copy(publicId = "ledger-b-1")
        val accepted = CompletableDeferred<Result<Expense>>()
        val fake = FakeReviewActions(listOf(a), activeLedgerFlow = ledger, activeLedgerIdProvider = { ledger.value })
        fake.saveAndConfirmResponder = { binding, baseline, _ ->
            assertEquals("ledger-a", binding.ledgerId)
            assertEquals(a, baseline)
            accepted.await()
        }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openMissingAmount(a)
        vm.saveAmountAndConfirm(a.id, 4200L)
        runCurrent()
        fake.pending = listOf(b, expense(2L, amountCents = null))
        ledger.value = "ledger-b"
        runCurrent()
        vm.openMissingAmount(b)
        val before = vm.uiState.value
        val skipped = vm.reviewSkippedIds.toSet()
        accepted.complete(Result.success(a.copy(originalAmountMinor = 4200L)))
        runCurrent()
        assertEquals(before.items, vm.uiState.value.items)
        assertEquals(before.activeSheet, vm.uiState.value.activeSheet)
        assertEquals(before.reviewRemaining, vm.uiState.value.reviewRemaining)
        assertEquals(before.message, vm.uiState.value.message)
        assertEquals(skipped, vm.reviewSkippedIds)
        assertEquals("ledger-a", fake.admissions.single().first.ledgerId)
        assertEquals(2, fake.admissions.single().second.rowIds.size)
    }

    @Test
    fun lateAdmissionCannotClearAnotherLedgersInProgressSameExpenseId() = review {
        val ledger = MutableStateFlow<String?>("ledger-a")
        val a = expense(1L, merchant = null)
        val b = expense(1L, merchant = null).copy(publicId = "ledger-b-1")
        val aAccepted = CompletableDeferred<Result<Expense>>()
        val fake = FakeReviewActions(listOf(a), activeLedgerFlow = ledger, activeLedgerIdProvider = { ledger.value })
        fake.saveResponder = { binding, baseline, _ ->
            if (binding.ledgerId == "ledger-a") {
                assertEquals(a, baseline)
                aAccepted.await()
            } else {
                assertEquals("ledger-b", binding.ledgerId)
                assertEquals(b, baseline)
                Result.success(b.copy(merchant = "B merchant"))
            }
        }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.openQuickMerchant(a)
        vm.saveQuickMerchant(a.id, "A merchant")
        runCurrent()
        fake.pending = listOf(b)
        ledger.value = "ledger-b"
        runCurrent()
        vm.openQuickMerchant(b)
        vm.saveQuickMerchant(b.id, "B merchant")
        runCurrent()
        val before = vm.uiState.value
        assertEquals(setOf(1L), before.actionInProgressIds)
        aAccepted.complete(Result.success(a.copy(merchant = "A merchant")))
        runCurrent()
        assertEquals(before.actionInProgressIds, vm.uiState.value.actionInProgressIds)
        assertEquals(before.items, vm.uiState.value.items)
        assertEquals(before.activeSheet, vm.uiState.value.activeSheet)
        assertEquals(before.bulkConfirm, vm.uiState.value.bulkConfirm)
        assertEquals(listOf("ledger-a", "ledger-b"), fake.admissions.map { it.first.ledgerId })
    }
}
