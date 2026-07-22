package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.StatsActions
import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
private fun statsTest(block: suspend TestScope.() -> Unit) = runTest {
    val dispatcher = StandardTestDispatcher(testScheduler)
    Dispatchers.setMain(dispatcher)
    try {
        block()
    } finally {
        Dispatchers.resetMain()
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class MonthlyStatsViewModelTest {
    @Test
    fun staleMonthRefreshDoesNotOverwriteCurrentSelection() = statsTest {
        val mayResponse = CompletableDeferred<Result<MonthlyStats>>()
        val aprilResponse = CompletableDeferred<Result<MonthlyStats>>()
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { month, _ ->
            if (month == "2026-04") {
                aprilResponse.await()
            } else {
                mayResponse.await()
            }
        }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        viewModel.setMonth("2026-04")
        advanceUntilIdle()

        mayResponse.complete(Result.success(statsForMonth("2026-05", total = 999000)))
        advanceUntilIdle()

        assertEquals("2026-04", viewModel.uiState.value.month)
        assertNull(viewModel.uiState.value.stats)

        aprilResponse.complete(Result.success(statsForMonth("2026-04", total = 111000)))
        advanceUntilIdle()

        assertEquals("2026-04", viewModel.uiState.value.month)
        assertEquals(111000L, viewModel.uiState.value.stats?.totalAmountCents)
        assertEquals("2026-04", viewModel.uiState.value.lifestyleStats?.month)
    }

    @Test
    fun statsSourceMarksBackendOnSuccess() = statsTest {
        val stats = FakeStatsActions()
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        assertEquals(StatsSource.Backend, viewModel.uiState.value.statsSource)
    }

    @Test
    fun primaryStatsStopsLoadingBeforeLifestyleCompletes() = statsTest {
        val lifestyleResponse = CompletableDeferred<Result<LifestyleStats>>()
        val stats = FakeStatsActions()
        stats.lifestyleStatsResponder = { lifestyleResponse.await() }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        assertEquals(StatsSource.Backend, viewModel.uiState.value.statsSource)
        assertFalse(viewModel.uiState.value.loading)
        assertNull(viewModel.uiState.value.lifestyleStats)

        lifestyleResponse.complete(Result.success(lifestyleForMonth("2026-05")))
        advanceUntilIdle()

        assertEquals("2026-05", viewModel.uiState.value.lifestyleStats?.month)
    }

    @Test
    fun duplicateRefreshForSameMonthAndTagIsCoalescedWhileInFlight() = statsTest {
        val primaryResponse = CompletableDeferred<Result<MonthlyStats>>()
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> primaryResponse.await() }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        runCurrent()
        assertTrue(viewModel.uiState.value.loading)
        assertEquals(1, stats.monthlyStatsCalls)

        viewModel.refresh()
        runCurrent()

        assertEquals(1, stats.monthlyStatsCalls)
        primaryResponse.complete(Result.success(statsForMonth("2026-05", total = 123000)))
        advanceUntilIdle()

        assertFalse(viewModel.uiState.value.loading)
        stats.monthlyStatsResponder = null
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(2, stats.monthlyStatsCalls)
    }

    @Test
    fun statsSourceMarksLocalFallbackOnBackendFailure() = statsTest {
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> Result.failure(RuntimeException("offline")) }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        // Seed local Room cache so the fallback path has something to compute against.
        stats.confirmedFlow.value = listOf(
            Expense(
                id = 1L,
                publicId = "e1",
                amountCents = 12345L,
                merchant = "本机",
                category = "餐饮",
                note = null,
                source = "android-qa",
                imagePath = null,
                thumbnailPath = null,
                imageHash = null,
                rawText = null,
                confidence = null,
                duplicateStatus = "none",
                duplicateOfId = null,
                duplicateReason = null,
                tags = "",
                valueScore = null,
                regretScore = null,
                status = "confirmed",
                expenseTime = "2026-05-12T10:15:00Z",
                createdAt = "2026-05-12T10:15:00Z",
                updatedAt = "2026-05-12T10:15:00Z",
                rowVersion = 1L,
                confirmedAt = "2026-05-12T10:15:00Z",
                rejectedAt = null,
            ),
        )
        // Default month falls back to YearMonth.now() — pin to the fixture's
        // month so this test stays passing as wall-clock moves past 2026-05.
        viewModel.setMonth("2026-05")
        advanceUntilIdle()

        assertEquals(StatsSource.LocalFallback, viewModel.uiState.value.statsSource)
        // 审计 8.4: a usable local fallback is data, not an error — no error card.
        assertNull(viewModel.uiState.value.statsLoadError)
    }

    @Test
    fun setTagMarksLocalFallbackUntilBackendTaggedStatsArrive() = statsTest {
        val taggedResponse = CompletableDeferred<Result<MonthlyStats>>()
        val stats = FakeStatsActions()
        stats.confirmedFlow.value = listOf(
            confirmedExpense(
                publicId = "tagged",
                amountCents = 2200L,
                expenseTime = "2026-05-12T10:15:00Z",
                tags = "coffee",
            ),
        )
        stats.monthlyStatsResponder = { month, tag ->
            if (tag == "coffee") {
                taggedResponse.await()
            } else {
                Result.success(statsForMonth(month ?: "2026-05", total = 9900L))
            }
        }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        viewModel.setMonth("2026-05")
        advanceUntilIdle()
        assertEquals(StatsSource.Backend, viewModel.uiState.value.statsSource)

        viewModel.setTag("coffee")
        runCurrent()

        assertEquals(StatsSource.LocalFallback, viewModel.uiState.value.statsSource)
        assertEquals(2200L, viewModel.uiState.value.stats?.totalAmountCents)
        assertTrue(viewModel.uiState.value.loading)

        taggedResponse.complete(Result.success(statsForMonth("2026-05", total = 3300L)))
        advanceUntilIdle()

        assertEquals(StatsSource.Backend, viewModel.uiState.value.statsSource)
        assertEquals(3300L, viewModel.uiState.value.stats?.totalAmountCents)
    }

    @Test
    fun totalFailureWithNoCacheSetsRetryableError() = statsTest {
        // 审计 8.4: a load that fails with nothing to render becomes a retryable error
        // state, not the empty card that reads like "没有数据".
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> Result.failure(RuntimeException("offline")) }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        viewModel.setMonth("2026-05")
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertNull(state.stats)
        assertEquals(StatsSource.None, state.statsSource)
        assertNotNull(state.statsLoadError)
        // The error card is the single failure surface — a loose message line
        // would render the same copy twice (对抗审 P2).
        assertNull(state.message)
    }

    @Test
    fun retryAfterTotalFailureClearsError() = statsTest {
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> Result.failure(RuntimeException("offline")) }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        viewModel.setMonth("2026-05")
        advanceUntilIdle()
        assertNotNull(viewModel.uiState.value.statsLoadError)

        // Retry goes through refresh() (the UI's onRetry); now the backend answers.
        stats.monthlyStatsResponder = null
        viewModel.refresh()
        advanceUntilIdle()

        assertNull(viewModel.uiState.value.statsLoadError)
        assertEquals(StatsSource.Backend, viewModel.uiState.value.statsSource)
    }

    // P4 stale-refresh: tags are loaded on init / ledger switch only, so after a tag
    // is deleted in settings the filter chips kept the dead tag. reloadTags() re-pulls
    // the authoritative list (StatsRoute calls it on the cross-screen refresh signal /
    // pull-to-refresh).
    @Test
    fun reloadTagsRePullsAuthoritativeTagList() = statsTest {
        val stats = FakeStatsActions()
        stats.tagList = listOf("餐饮", "还好")
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()
        assertEquals(listOf("餐饮", "还好"), viewModel.uiState.value.tags)

        // A tag was deleted in settings → the authoritative list drops it.
        stats.tagList = listOf("餐饮")
        viewModel.reloadTags()
        advanceUntilIdle()
        assertEquals(listOf("餐饮"), viewModel.uiState.value.tags)
        assertEquals(StatsFilterOptionsLoadState.Loaded, viewModel.uiState.value.tagsLoadState)
    }

    @Test
    fun monthOptionsKeepSelectedMonthWhenBackendHasNoRowsForIt() = statsTest {
        val stats = FakeStatsActions()
        stats.monthList = listOf("2027-06", "2026-06", "2026-05")
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        viewModel.setMonth("2026-07")
        advanceUntilIdle()

        assertTrue("2026-07" in viewModel.uiState.value.months)
        assertEquals("2026-07", viewModel.uiState.value.months.first())
    }

    @Test
    fun localDailyTrendIsBoundedToSelectedMonth() = statsTest {
        val stats = FakeStatsActions()
        stats.confirmedFlow.value = listOf(
            confirmedExpense(publicId = "may", amountCents = 1200L, expenseTime = "2026-05-31"),
            confirmedExpense(publicId = "june", amountCents = 980000L, expenseTime = "2026-06-30"),
        )
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        viewModel.setMonth("2026-05")
        advanceUntilIdle()

        val nonZeroDays = viewModel.uiState.value.dailyTrend.filter { it.amountCents > 0L }
        assertEquals(1, nonZeroDays.size)
        assertEquals("2026-05-31", nonZeroDays.single().date)
        assertEquals(1200L, nonZeroDays.single().amountCents)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class MonthlyStatsFilterOptionsViewModelTest {
    @Test
    fun dataQualityLoadsEvenWhenMonthlyStatsFails() = statsTest {
        // PR #230 round 12 review claimed the DQ load is bound to the monthly
        // success path — pin the actual contract: the failure path also fires
        // the supplemental DQ load (handleStatsFailure → loadSupplemental).
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> Result.failure(RuntimeException("offline")) }
        stats.dataQualityResponder = {
            Result.success(
                DataQualitySummary(
                    pendingTotal = 3,
                    missingAmount = 0,
                    missingMerchant = 2,
                    missingCategory = 0,
                    missingCategoryPending = 0,
                    missingCategoryConfirmed = 0,
                    suspectedDuplicates = 0,
                    confirmedWithoutImage = 0,
                    readyToConfirm = 0,
                    readyToConfirmCategorized = 0,
                    oldestPendingAgeDays = 1,
                    generatedAt = "2026-05-13T00:00:00Z",
                )
            )
        }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals(DataQualityLoadState.Loaded, state.dataQualityLoadState)
        assertEquals(2, state.dataQuality?.missingMerchant)
        // The monthly failure still surfaces its own error alongside.
        assertNotNull(state.statsLoadError)
    }

    @Test
    fun dataQualityFailureIsItsOwnErrorStateWhenStatsAlsoFail() = statsTest {
        val stats = FakeStatsActions()
        stats.monthlyStatsResponder = { _, _ -> Result.failure(RuntimeException("offline")) }
        stats.dataQualityResponder = { Result.failure(RuntimeException("dq offline")) }
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        val state = viewModel.uiState.value
        assertEquals(DataQualityLoadState.Failed, state.dataQualityLoadState)
        assertNotNull(state.dataQualityError)
        assertNull(state.dataQuality)
    }

    @Test
    fun filterOptionFailuresAreExplicitStatesNotLoadedEmptyFacts() = statsTest {
        val stats = FakeStatsActions()
        stats.monthListResult = Result.failure(RuntimeException("months offline"))
        stats.tagListResult = Result.failure(RuntimeException("tags offline"))
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()

        assertEquals(StatsFilterOptionsLoadState.Failed, viewModel.uiState.value.monthsLoadState)
        assertEquals(StatsFilterOptionsLoadState.Failed, viewModel.uiState.value.tagsLoadState)
        assertEquals(emptyList(), viewModel.uiState.value.months)
        assertEquals(emptyList(), viewModel.uiState.value.tags)
    }

    @Test
    fun tagRefreshFailurePreservesExistingReadableChoices() = statsTest {
        val stats = FakeStatsActions()
        stats.tagList = listOf("餐饮", "通勤")
        val viewModel = MonthlyStatsViewModel(
            repository = stats,
            recurringRepository = FakeStatsRecurringActions(),
        )
        advanceUntilIdle()
        assertEquals(listOf("餐饮", "通勤"), viewModel.uiState.value.tags)
        assertEquals(StatsFilterOptionsLoadState.Loaded, viewModel.uiState.value.tagsLoadState)

        stats.tagListResult = Result.failure(RuntimeException("offline"))
        viewModel.reloadTags()
        advanceUntilIdle()

        assertEquals(StatsFilterOptionsLoadState.Failed, viewModel.uiState.value.tagsLoadState)
        assertEquals(listOf("餐饮", "通勤"), viewModel.uiState.value.tags)
    }
}

private class FakeStatsActions : StatsActions {
    val ledgerFlow = MutableStateFlow<String?>("owner")
    val confirmedFlow = MutableStateFlow<List<Expense>>(emptyList())
    var monthlyStatsResponder: (suspend (String?, String?) -> Result<MonthlyStats>)? = null
    var lifestyleStatsResponder: (suspend (String?) -> Result<LifestyleStats>)? = null
    var monthList: List<String> = listOf("2026-05", "2026-04")
    var monthListResult: Result<List<String>>? = null
    var tagList: List<String> = emptyList()
    var tagListResult: Result<List<String>>? = null
    var monthlyStatsCalls = 0
    var dataQualityResponder: (suspend () -> Result<DataQualitySummary>)? = null

    override fun observeActiveLedgerId(): Flow<String?> = ledgerFlow

    override fun observeConfirmed(): Flow<List<Expense>> = confirmedFlow

    override fun monthlyBudgetCents(): Long? = null

    override fun lastUploadAt(): String? = null

    override suspend fun months(): Result<List<String>> = monthListResult ?: Result.success(monthList)

    override suspend fun tags(): Result<List<String>> = tagListResult ?: Result.success(tagList)

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> {
        monthlyStatsCalls++
        monthlyStatsResponder?.let { return it(month, tag) }
        return Result.success(statsForMonth(month ?: "2026-05"))
    }

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> =
        lifestyleStatsResponder?.invoke(month)
            ?: Result.success(lifestyleForMonth(month ?: "2026-05"))

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = Result.success(emptyList())

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> =
        dataQualityResponder?.invoke()
            ?: Result.success(
                DataQualitySummary(
                    pendingTotal = 0,
                    missingAmount = 0,
                    missingMerchant = 0,
                    missingCategory = 0,
                    missingCategoryPending = 0,
                    missingCategoryConfirmed = 0,
                    suspectedDuplicates = 0,
                    confirmedWithoutImage = 0,
                    readyToConfirm = 0,
                    readyToConfirmCategorized = 0,
                    oldestPendingAgeDays = null,
                    generatedAt = "2026-05-13T00:00:00Z",
                )
            )
}

private class FakeStatsRecurringActions : RecurringActions {
    override fun canModifyLedger(): Boolean = true

    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> = Result.success(emptyList())

    override suspend fun candidates(): Result<List<RecurringCandidate>> = Result.success(emptyList())

    override suspend fun detail(publicId: String, month: String?): Result<RecurringItem> =
        Result.failure(IllegalArgumentException("not used"))

    override suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> = Result.failure(IllegalArgumentException("not used"))

    override suspend fun pause(publicId: String, expectedRowVersion: Long): Result<RecurringItem> =
        Result.failure(IllegalArgumentException("not used"))

    override suspend fun resume(publicId: String, expectedRowVersion: Long): Result<RecurringItem> =
        Result.failure(IllegalArgumentException("not used"))

    override suspend fun archive(publicId: String): Result<RecurringItem> =
        Result.failure(IllegalArgumentException("not used"))
}

private fun statsForMonth(month: String, total: Long = 0): MonthlyStats =
    MonthlyStats(
        month = month,
        totalAmountCents = total,
        count = if (total > 0) 1 else 0,
        byCategory = emptyList(),
    )

private fun lifestyleForMonth(month: String): LifestyleStats =
    LifestyleStats(
        month = month,
        aiSubscriptionAmountCents = 0,
        digitalAmountCents = 0,
        maxExpense = null,
        recent7DaysAmountCents = 0,
        frequentMerchants = emptyList(),
    )

private fun confirmedExpense(
    publicId: String,
    amountCents: Long,
    expenseTime: String,
    tags: String? = null,
): Expense =
    Expense(
        id = publicId.hashCode().toLong(),
        publicId = publicId,
        amountCents = amountCents,
        merchant = "测试商家",
        category = "餐饮",
        note = null,
        source = "android-test",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = tags.orEmpty(),
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = expenseTime,
        createdAt = expenseTime,
        updatedAt = expenseTime,
        rowVersion = 1L,
        confirmedAt = expenseTime,
        rejectedAt = null,
    )
