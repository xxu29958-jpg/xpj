package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/** Currency and OCC come from the same budget response; debt reads no longer participate. */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetViewModelCurrencyRaceTest {
    @Test
    fun jpyRecordBackfillsWithoutScaling() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 1200L).copy(homeCurrencyCode = "JPY"))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, vm.uiState.value.formCurrency)
        assertEquals("1200", vm.uiState.value.form.totalAmount)
        assertEquals(1L, vm.uiState.value.form.expectedRowVersion)
    }

    @Test
    fun offlineStartRecoversByReadingTheBudgetBeforeAnyWrite() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 1200L).copy(homeCurrencyCode = "JPY"))
        fake.monthlyBudgetResponder = { Result.failure(IllegalStateException("offline")) }
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals(null, vm.uiState.value.formCurrency)
        assertEquals("", vm.uiState.value.form.totalAmount)
        assertNotNull(vm.uiState.value.loadError)
        vm.save()
        advanceUntilIdle()
        assertEquals(0, fake.commands.savedRequests.size)
        fake.monthlyBudgetResponder = null
        vm.refresh()
        advanceUntilIdle()
        assertEquals("1200", vm.uiState.value.form.totalAmount)
        vm.save()
        advanceUntilIdle()
        assertEquals("JPY", fake.commands.savedRequests.single().homeCurrencyCode)
        assertEquals(1200L, fake.commands.savedRequests.single().totalAmountCents)
    }

    @Test
    fun refreshPreservesEditedAmountCurrencyAndObservedVersion() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 1200L).copy(homeCurrencyCode = "JPY"))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        vm.updateTotalAmount(" 1500 ")
        fake.budget = fake.budget.copy(homeCurrencyCode = "CNY", rowVersion = 2L, totalAmountCents = 300000)
        vm.refresh()
        advanceUntilIdle()
        assertEquals(" 1500 ", vm.uiState.value.form.totalAmount)
        assertEquals(CurrencyCode.JPY, vm.uiState.value.formCurrency)
        assertEquals(1L, vm.uiState.value.form.expectedRowVersion)
        assertEquals(2L, vm.uiState.value.budget?.rowVersion)
        vm.save()
        advanceUntilIdle()
        assertEquals("JPY", fake.commands.savedRequests.single().homeCurrencyCode)
        assertEquals(1500L, fake.commands.savedRequests.single().totalAmountCents)
        assertEquals(1L, fake.commands.savedRequests.single().expectedRowVersion)
    }

    @Test
    fun ledgerSwitchDoesNotReuseThePreviousRecordCurrency() = budgetTest {
        val access = MutableStateFlow(raceAccess("ledger-a"))
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 300000), activeAccessFlow = access)
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals("3000", vm.uiState.value.form.totalAmount)
        fake.budget = fake.budget.copy(homeCurrencyCode = "JPY")
        access.value = raceAccess("ledger-b")
        advanceUntilIdle()
        assertEquals(CurrencyCode.JPY, vm.uiState.value.formCurrency)
        assertEquals("300000", vm.uiState.value.form.totalAmount)
    }
}

private fun raceAccess(ledgerId: String): LedgerAccessContext = LedgerAccessContext(
    LogicalSessionBinding("https://api.example.com", ledgerId, "owner", "session-$ledgerId", "binding-$ledgerId"),
    canModify = true,
)
