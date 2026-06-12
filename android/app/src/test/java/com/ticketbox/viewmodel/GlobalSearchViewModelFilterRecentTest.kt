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

// Filter-chips / amount-match / recent-search / truncation tests, split from
// GlobalSearchViewModelTest to stay inside the detekt functions-per-class budget.
@OptIn(ExperimentalCoroutinesApi::class)
class GlobalSearchViewModelFilterRecentTest {
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
    fun numericQueryAlsoMatchesExactAmountAcrossBuckets() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "无关", amountCents = 1250L)),
            confirmed = listOf(
                // home-leg ¥12.50 match
                expense(id = 2, status = "confirmed", merchant = "无关", amountCents = 1250L),
                // original foreign-leg 1250 minor match (home amount differs)
                expense(id = 3, status = "confirmed", merchant = "无关", amountCents = 9900L)
                    .copy(originalAmountMinor = 1250L),
                // not 12.50 — must NOT match
                expense(id = 4, status = "confirmed", merchant = "无关", amountCents = 800L),
            ),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("¥12.50")
        advanceUntilIdle()

        val ids = vm.uiState.value.results.map { it.expense.id }.toSet()
        assertEquals(setOf(1L, 2L, 3L), ids)
    }

    @Test
    fun categoryAndMonthChipsNarrowResultsWithAndSemantics() = searchTest {
        val fake = FakeGlobalSearchActions(
            confirmed = listOf(
                expense(id = 1, status = "confirmed", merchant = "Cafe May", category = "餐饮").copy(expenseTime = "2026-05-10T08:00:00Z"),
                expense(id = 2, status = "confirmed", merchant = "Cafe June", category = "餐饮").copy(expenseTime = "2026-06-10T08:00:00Z"),
                expense(id = 3, status = "confirmed", merchant = "Shop May", category = "购物").copy(expenseTime = "2026-05-12T08:00:00Z"),
            ),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        // Facets are derived from the caches.
        assertTrue("2026-05" in vm.uiState.value.availableMonths)
        assertTrue("餐饮" in vm.uiState.value.availableCategories)

        // Chip-only (blank query) filters; AND with category + month.
        vm.setCategoryFilter("餐饮")
        vm.setMonthFilter("2026-05")
        advanceUntilIdle()

        assertEquals(listOf(1L), vm.uiState.value.results.map { it.expense.id })

        // Adding a text term ANDs further.
        vm.setQuery("June")
        advanceUntilIdle()
        assertTrue(vm.uiState.value.results.isEmpty())
    }

    @Test
    fun commitSearchPersistsRecentQueriesDedupedNewestFirstAndCapped() = searchTest {
        val fake = FakeGlobalSearchActions()
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        // Commit 9 distinct queries; cap is 8 so the oldest drops, newest first.
        (1..9).forEach { n ->
            vm.setQuery("q$n")
            vm.commitSearch()
        }
        advanceUntilIdle()
        assertEquals(8, vm.uiState.value.recentSearches.size)
        assertEquals("q9", vm.uiState.value.recentSearches.first())
        assertTrue("q1" !in vm.uiState.value.recentSearches)

        // Re-committing an existing query moves it to the front (no dup).
        vm.setQuery("q3")
        vm.commitSearch()
        advanceUntilIdle()
        assertEquals("q3", vm.uiState.value.recentSearches.first())
        assertEquals(8, vm.uiState.value.recentSearches.size)
        assertEquals(1, vm.uiState.value.recentSearches.count { it == "q3" })
        // Persisted through the store, not just in memory.
        assertEquals(vm.uiState.value.recentSearches, fake.savedRecent)
    }

    @Test
    fun blankCommitIsIgnoredAndRecentLoadsFromStoreOnInit() = searchTest {
        val fake = FakeGlobalSearchActions(initialRecent = listOf("地铁", "咖啡"))
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        // Seeded history is surfaced.
        assertEquals(listOf("地铁", "咖啡"), vm.uiState.value.recentSearches)

        // Whitespace-only commit is a no-op.
        vm.setQuery("   ")
        vm.commitSearch()
        advanceUntilIdle()
        assertEquals(listOf("地铁", "咖啡"), vm.uiState.value.recentSearches)
    }

    @Test
    fun applyRecentSearchRefillsTheBoxAndRunsTheSearch() = searchTest {
        val fake = FakeGlobalSearchActions(
            confirmed = listOf(expense(id = 7, status = "confirmed", merchant = "地铁通勤")),
            initialRecent = listOf("地铁"),
        )
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.applyRecentSearch("地铁")
        advanceUntilIdle()

        assertEquals("地铁", vm.uiState.value.query)
        assertEquals(listOf(7L), vm.uiState.value.results.map { it.expense.id })
    }

    @Test
    fun clearRecentSearchesWipesHistoryAndStore() = searchTest {
        val fake = FakeGlobalSearchActions(initialRecent = listOf("地铁", "咖啡"))
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.clearRecentSearches()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.recentSearches.isEmpty())
        assertTrue(fake.savedRecent.isEmpty())
    }

    @Test
    fun flagsTruncationWhenABucketExceedsTheCap() = searchTest {
        val confirmed = (1..25).map { n ->
            expense(id = n.toLong(), status = "confirmed", merchant = "Cafe $n", category = "餐饮")
        }
        val fake = FakeGlobalSearchActions(confirmed = confirmed)
        val vm = GlobalSearchViewModel(fake)
        advanceUntilIdle()

        vm.setQuery("Cafe")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(25, state.confirmedMatchCount)
        // Capped to the per-bucket limit, with the truncation flag set.
        assertEquals(state.resultLimit, state.results.size)
        assertTrue(state.truncated)
    }
}
