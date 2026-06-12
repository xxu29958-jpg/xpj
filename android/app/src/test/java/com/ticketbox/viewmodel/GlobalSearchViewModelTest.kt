package com.ticketbox.viewmodel

import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class GlobalSearchViewModelTest {
    private fun searchTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun searchesPendingAndConfirmedCachesWithoutPerQueryNetworkCalls() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "SearchCafe Pending")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "SearchCafe Confirmed")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("SearchCafe")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, fake.fetchPendingCalls)
        assertEquals(1, state.pendingMatchCount)
        assertEquals(1, state.confirmedMatchCount)
        assertEquals(
            listOf(GlobalSearchResultKind.Pending, GlobalSearchResultKind.Confirmed),
            state.results.map { it.kind },
        )

        vm.setQuery("Confirmed")
        advanceUntilIdle()
        assertEquals(1, fake.fetchPendingCalls)
        assertEquals(listOf(2L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun scopesResultsWithoutChangingTheUnderlyingMatches() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "Family Cafe")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Family Cafe")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Cafe")
        vm.setScope(GlobalSearchScope.Confirmed)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, state.pendingMatchCount)
        assertEquals(1, state.confirmedMatchCount)
        assertEquals(listOf(GlobalSearchResultKind.Confirmed), state.results.map { it.kind })
        assertEquals(listOf(2L), state.results.map { it.expense.id })
    }

    @Test
    fun pendingFailureKeepsConfirmedCacheSearchable() = searchTest {
        val fake = FakeGlobalSearchActions(
            pendingResult = Result.failure(IllegalStateException("pending offline")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Local Cafe")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Local")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.pendingLoaded)
        assertEquals(UiText.raw("pending offline"), state.message)
        assertEquals(listOf(2L), state.results.map { it.expense.id })
    }

    @Test
    fun activeLedgerChangeClearsSearchCachesAndReloadsPending() = searchTest {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeGlobalSearchActions(
            activeLedgerFlow = ledgerFlow,
            pending = listOf(expense(id = 1, status = "pending", merchant = "Old Cafe")),
            confirmed = listOf(expense(id = 2, status = "confirmed", merchant = "Old Confirmed")),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Old")
        advanceUntilIdle()
        assertEquals(listOf(1L, 2L), vm.uiState.value.results.map { it.expense.id })

        fake.pendingResult = Result.success(listOf(expense(id = 3, status = "pending", merchant = "New Cafe")))
        ledgerFlow.value = "family"
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(0, vm.uiState.value.confirmedMatchCount)
        assertTrue(vm.uiState.value.results.isEmpty())

        vm.setQuery("New")
        advanceUntilIdle()
        assertEquals(listOf(3L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun stalePendingResponseAfterLedgerChangeIsIgnored() = searchTest {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val firstResponse = CompletableDeferred<Result<List<Expense>>>()
        val secondResponse = CompletableDeferred<Result<List<Expense>>>()
        val fake = FakeGlobalSearchActions(activeLedgerFlow = ledgerFlow)
        var fetchIndex = 0
        fake.fetchPendingResponder = {
            fetchIndex += 1
            if (fetchIndex == 1) firstResponse.await() else secondResponse.await()
        }
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Cafe")
        ledgerFlow.value = "family"
        advanceUntilIdle()

        firstResponse.complete(Result.success(listOf(expense(id = 4, status = "pending", merchant = "Old Cafe"))))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.results.isEmpty())

        secondResponse.complete(Result.success(listOf(expense(id = 5, status = "pending", merchant = "New Cafe"))))
        advanceUntilIdle()

        assertEquals(2, fake.fetchPendingCalls)
        assertEquals(listOf(5L), vm.uiState.value.results.map { it.expense.id })
    }
}
