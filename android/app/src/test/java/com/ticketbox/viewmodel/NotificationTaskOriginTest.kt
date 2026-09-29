package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class NotificationTaskOriginTest {
    private val binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding")

    @Test fun originalBudgetDoesNotBecomeAnotherAccountsSameMonthOrLoseTheOriginalInput() = budgetTest {
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
        val repo = FakeBudgetActions(budget(), activeAccessFlow = access)
        val vm = BudgetViewModel(repo, "2026-07", originalBinding = binding)
        advanceUntilIdle()
        vm.updateTotalAmount("321.09")
        val original = vm.uiState.value
        access.value = LedgerAccessContext(binding.copy(ownerKey = "another-owner", bindingRevision = "new"), true)
        advanceUntilIdle()
        assertEquals(listOf("2026-07"), repo.loadedMonths)
        assertEquals(original.form, vm.uiState.value.form)
        assertEquals(binding, vm.uiState.value.binding)
    }

    @Test fun credentialRenewalStillOpensTheOriginalMonthButRebindingBeforeConstructionCannotReadIt() = budgetTest {
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding.copy(bindingRevision = "renewed"), true))
        val repo = FakeBudgetActions(budget(), activeAccessFlow = access)
        val vm = BudgetViewModel(repo, "2026-07", originalBinding = binding)
        advanceUntilIdle()
        assertEquals(listOf("2026-07"), repo.loadedMonths)
        assertEquals("renewed", vm.uiState.value.binding?.bindingRevision)
        access.value = LedgerAccessContext(binding.copy(serverUrl = "https://second.example.test"), true)
        val delayed = BudgetViewModel(repo, "2026-07", originalBinding = binding)
        advanceUntilIdle()
        assertNull(delayed.uiState.value.budget)
        assertEquals(listOf("2026-07"), repo.loadedMonths)
    }

    @Test fun aNotificationCannotReadTheOtherAccountsExpenseWithTheSameNumericId() = budgetTest {
        val repo = FakeExpenseEditActions()
        var reads = 0
        repo.fetchExpenseResponder = { reads++; Result.success(repo.baseExpense) }
        val vm = ExpenseEditViewModel(7, repo, originalBinding = repo.binding.copy(ownerKey = "original-owner"))
        advanceUntilIdle()
        assertEquals(0, reads)
        assertEquals(0, repo.localCacheCalls)
        assertNull(vm.uiState.value.expense)
        assertEquals(false, vm.uiState.value.expenseLoading)
    }

    @Test fun aRefusedOriginalExpenseCannotReappearFromCacheWhileOfflineReadingStillWorks() = budgetTest {
        val refused = FakeExpenseEditActions().apply {
            fetchExpenseResponder = { Result.failure(com.ticketbox.data.repository.RepositoryException(
                "Original expense is no longer readable", httpStatusCode = 403)) }
        }
        val denied = ExpenseEditViewModel(7, refused, originalBinding = refused.binding)
        advanceUntilIdle()
        assertNull(denied.uiState.value.expense)
        assertEquals(0, refused.localCacheCalls)

        val offline = FakeExpenseEditActions().apply {
            fetchExpenseResponder = { Result.failure(java.io.IOException("offline")) }
        }
        val retained = ExpenseEditViewModel(7, offline, originalBinding = offline.binding)
        advanceUntilIdle()
        assertEquals(offline.baseExpense, retained.uiState.value.expense)
        assertEquals(1, offline.localCacheCalls)
    }
}
