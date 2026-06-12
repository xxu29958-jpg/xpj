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

    @Test
    fun numericQueryAlsoMatchesExactAmountAcrossBuckets() = searchTest {
        val fake = FakeGlobalSearchActions(
            pending = listOf(expense(id = 1, status = "pending", merchant = "无关", amountCents = 1250L)),
            confirmed = listOf(
                // home-leg ¥12.50 match
                expense(id = 2, status = "confirmed", merchant = "无关", amountCents = 1250L),
                // original foreign-leg 1250 minor match (home amount differs)
                expense(id = 3, status = "confirmed", merchant = "无关", amountCents = 9900L, originalAmountMinor = 1250L),
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
                expense(id = 1, status = "confirmed", merchant = "Cafe May", category = "餐饮", expenseTime = "2026-05-10T08:00:00Z"),
                expense(id = 2, status = "confirmed", merchant = "Cafe June", category = "餐饮", expenseTime = "2026-06-10T08:00:00Z"),
                expense(id = 3, status = "confirmed", merchant = "Shop May", category = "购物", expenseTime = "2026-05-12T08:00:00Z"),
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

private class FakeGlobalSearchActions(
    private val activeLedgerFlow: Flow<String?> = MutableStateFlow("owner"),
    pending: List<Expense> = emptyList(),
    pendingResult: Result<List<Expense>> = Result.success(pending),
    confirmed: List<Expense> = emptyList(),
    initialRecent: List<String> = emptyList(),
) : GlobalSearchActions {
    private val confirmedFlow = MutableStateFlow(confirmed)
    var pendingResult = pendingResult
    var fetchPendingResponder: (suspend () -> Result<List<Expense>>)? = null
    var fetchPendingCalls: Int = 0
        private set

    // Mirrors the SharedPreferences-backed store: last write wins, read-back
    // returns it. Lets the VM tests assert persistence round-trips.
    var savedRecent: List<String> = initialRecent
        private set

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun observeConfirmed(): Flow<List<Expense>> = confirmedFlow

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        fetchPendingResponder?.let { return it() }
        return pendingResult
    }

    override fun recentSearches(): List<String> = savedRecent

    override fun saveRecentSearches(queries: List<String>) {
        savedRecent = queries
    }
}

private fun expense(
    id: Long,
    status: String,
    merchant: String,
    amountCents: Long? = 1200L,
    category: String = "餐饮",
    expenseTime: String? = "2026-05-17T08:00:00Z",
    originalAmountMinor: Long? = null,
): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    originalAmountMinor = originalAmountMinor,
    merchant = merchant,
    category = category,
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
    expenseTime = expenseTime,
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = if (status == "confirmed") "2026-05-17T08:01:00Z" else null,
    rejectedAt = null,
)
