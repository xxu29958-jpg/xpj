package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.ExpenseFactOriginalInput
import com.ticketbox.data.repository.ExpenseFundingInput
import com.ticketbox.data.repository.fundingInputAdapter
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseRecoveredSaveTest {
    @Test fun `separate save preserves funding but cold restore uses the latest reviewed edits`() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val fake = FakeExpenseEditActions()
            val funding = fundingInputAdapter.toJson(listOf(ExpenseFundingInput("part", "account", 1,
                "厦门", "CNY", "CNY", "10.00", "10.00")))
            val recovered = ExpenseFactInputDraft(fake.baseExpense, fundingJson = funding,
                confirmationChanges = ExpenseUpdateRequest(merchant = "A", category = null, note = null,
                    expenseTime = null, tags = null, valueScore = null, regretScore = null))
            val input = ExpenseFactOriginalInput(fake.binding, 7, "pending_funding", "original",
                ExpenseFactInputCodec.encode(recovered))
            fake.originalInputs.saveFactInput(null, input).getOrThrow()
            val vm = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            assertEquals("A", vm.uiState.value.confirmationChanges?.merchant)
            fake.saveOfflineResponder = { _, _, expense ->
                Result.success(ExpenseCommandAcceptance(expense.copy(merchant = "B"), listOf(11)))
            }
            vm.save(ExpenseDraft(amountCents = null, merchant = "B", category = null, note = null,
                expenseTime = null, tags = null, valueScore = null, regretScore = null))
            advanceUntilIdle()
            assertEquals(1, fake.saveCalls)
            fake.fetchExpenseResponder = { Result.success(fake.baseExpense.copy(merchant = "B", rowVersion = 2)) }
            val cold = ExpenseEditViewModel(7, fake)
            advanceUntilIdle()
            assertEquals("B", cold.uiState.value.expense?.merchant)
            assertEquals("B", cold.uiState.value.confirmationChanges?.merchant)
            assertEquals(funding, cold.uiState.value.fundingJson)
            assertTrue(cold.uiState.value.fundingReady)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }
}
