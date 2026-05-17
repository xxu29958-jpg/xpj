package com.ticketbox.viewmodel

import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.Expense
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
        assertEquals("pending offline", state.message)
        assertEquals(listOf(2L), state.results.map { it.expense.id })
    }
}

private class FakeGlobalSearchActions(
    pending: List<Expense> = emptyList(),
    pendingResult: Result<List<Expense>> = Result.success(pending),
    confirmed: List<Expense> = emptyList(),
) : GlobalSearchActions {
    private val confirmedFlow = MutableStateFlow(confirmed)
    private val pendingResult = pendingResult
    var fetchPendingCalls: Int = 0
        private set

    override fun observeConfirmed(): Flow<List<Expense>> = confirmedFlow

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        return pendingResult
    }
}

private fun expense(
    id: Long,
    status: String,
    merchant: String,
): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = 1200L,
    merchant = merchant,
    category = "餐饮",
    note = "家庭周末",
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = "Search raw text",
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = "family",
    valueScore = null,
    regretScore = null,
    status = status,
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    confirmedAt = if (status == "confirmed") "2026-05-17T08:01:00Z" else null,
    rejectedAt = null,
)
