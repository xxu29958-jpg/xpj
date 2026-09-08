package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetDraftContinuityTest {
    @Test
    fun changingMonthPreservesRawAmountsAndTheirObservedBasis() = budgetTest {
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY"))
        val vm = BudgetViewModel(owner, initialMonth = "2026-05")
        advanceUntilIdle()
        vm.updateTotalAmount(" 1500 ")
        vm.updateCategoryRow(0, "原分类", "非法输入")
        val original = vm.uiState.value.form
        vm.nextMonth()
        advanceUntilIdle()
        vm.previousMonth()
        advanceUntilIdle()
        assertEquals(original, vm.uiState.value.form)
    }

    @Test
    fun recreatedEditorRestoresItsRawDraftWithoutAdoptingNewCurrencyOrVersion() = budgetTest {
        val savedState = SavedStateHandle()
        val owner = FakeBudgetActions(budget = budget().copy(homeCurrencyCode = "JPY"))
        val first = BudgetViewModel(owner, initialMonth = "2026-05", savedStateHandle = savedState)
        advanceUntilIdle()
        first.updateTotalAmount(" 1500 ")
        first.updateRolloverAmount("-20")
        first.updateCategoryRow(0, "原分类", "非法输入")
        val original = first.uiState.value.form
        owner.budget = owner.budget.copy(homeCurrencyCode = "CNY", rowVersion = 2)
        val restored = BudgetViewModel(owner, initialMonth = "2026-05", savedStateHandle = savedState)
        advanceUntilIdle()
        assertEquals(original, restored.uiState.value.form)
        assertEquals("CNY", restored.uiState.value.budget?.homeCurrencyCode)
        assertEquals(2L, restored.uiState.value.budget?.rowVersion)
        assertEquals(0, owner.savedRequests.size)
    }
}
