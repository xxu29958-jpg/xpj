package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.repository.BudgetSavePayload
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingBudgetSave
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetDraftQueueTransferTest {
    @Test
    fun oldAndroidSnapshotCannotResubmitTheQueuedOriginal() = budgetTest {
        val state = SavedStateHandle()
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val first = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        first.updateTotalAmount(" 1200 ")
        val oldSnapshot = SavedStateHandle(state.keys().associateWith { state.get<Any?>(it) })
        first.save()
        advanceUntilIdle()
        assertEquals(1, owner.savedRequests.size)
        owner.saves.value = listOf(pendingBudget())
        owner.budget = owner.budget.copy(homeCurrencyCode = "CNY", rowVersion = 3)
        val restored = BudgetViewModel(owner, "2026-05", savedStateHandle = oldSnapshot)
        advanceUntilIdle()
        assertFalse(restored.uiState.value.formDirty)
        assertTrue(restored.uiState.value.hasPendingSave)
        assertEquals("JPY", restored.uiState.value.form.homeCurrencyCode)
        assertEquals(1L, restored.uiState.value.form.expectedRowVersion)
        restored.save()
        advanceUntilIdle()
        assertEquals(1, owner.savedRequests.size)
        val accepted = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2)
        owner.saves.value = listOf(pendingBudget().let { it.copy(row = it.row.copy(status = PendingMutationStatus.Done), receipt = accepted) })
        advanceUntilIdle()
        assertFalse(restored.uiState.value.hasPendingSave)
        assertEquals("CNY", restored.uiState.value.budget?.homeCurrencyCode)
        assertEquals(1, owner.savedRequests.size)
    }

    @Test
    fun completedEarlierEditDoesNotEraseANewRawDraft() = budgetTest {
        val state = SavedStateHandle()
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY", nonMonthlyAmountCents = 0))
        val vm = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        vm.updateTotalAmount(" 1500 ")
        val original = vm.uiState.value.form
        owner.saves.value = listOf(pendingBudget().let { it.copy(
            row = it.row.copy(status = PendingMutationStatus.Done),
            receipt = budget(totalAmountCents = 1200).copy(homeCurrencyCode = "JPY", rowVersion = 2),
        ) })
        advanceUntilIdle()
        assertEquals(original, vm.uiState.value.form)
        assertTrue(vm.uiState.value.formDirty)
        val restored = BudgetViewModel(owner, "2026-05", savedStateHandle = state)
        advanceUntilIdle()
        assertEquals(original, restored.uiState.value.form)
        assertTrue(restored.uiState.value.formDirty)
        assertEquals(0, owner.savedRequests.size)
    }

    private fun pendingBudget() = PendingBudgetSave(
        row = OutboxRow(id = 1, serverUrl = "https://api.example.com", ledgerId = "owner",
            type = PendingMutationType.SaveMonthlyBudget, targetId = "monthly_budget:2026-05", payloadJson = "{}",
            expectedRowVersion = 1, status = PendingMutationStatus.Pending, retryCount = 0, lastError = null,
            createdAt = "2026-05-01T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "budget-original"),
        intent = BudgetSavePayload(1, "2026-05", "UTC", BudgetMonthlyUpdateRequestDto("JPY", null, 1200)),
        receipt = null,
    )
}
