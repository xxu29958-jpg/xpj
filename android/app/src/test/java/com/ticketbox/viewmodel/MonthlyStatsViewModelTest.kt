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
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class MonthlyStatsViewModelTest {
    private fun statsTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

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
                confirmedAt = "2026-05-12T10:15:00Z",
                rejectedAt = null,
            ),
        )
        advanceUntilIdle()

        assertEquals(StatsSource.LocalFallback, viewModel.uiState.value.statsSource)
    }
}

private class FakeStatsActions : StatsActions {
    val ledgerFlow = MutableStateFlow<String?>("owner")
    val confirmedFlow = MutableStateFlow<List<Expense>>(emptyList())
    var monthlyStatsResponder: (suspend (String?, String?) -> Result<MonthlyStats>)? = null

    override fun observeActiveLedgerId(): Flow<String?> = ledgerFlow

    override fun observeConfirmed(): Flow<List<Expense>> = confirmedFlow

    override fun monthlyBudgetCents(): Long? = null

    override fun lastUploadAt(): String? = null

    override suspend fun months(): Result<List<String>> = Result.success(listOf("2026-05", "2026-04"))

    override suspend fun tags(): Result<List<String>> = Result.success(emptyList())

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> {
        monthlyStatsResponder?.let { return it(month, tag) }
        return Result.success(statsForMonth(month ?: "2026-05"))
    }

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> =
        Result.success(
            LifestyleStats(
                month = month ?: "2026-05",
                aiSubscriptionAmountCents = 0,
                digitalAmountCents = 0,
                maxExpense = null,
                recent7DaysAmountCents = 0,
                frequentMerchants = emptyList(),
            )
        )

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = Result.success(emptyList())

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> =
        Result.success(
            DataQualitySummary(
                pendingTotal = 0,
                missingAmount = 0,
                missingMerchant = 0,
                missingCategory = 0,
                suspectedDuplicates = 0,
                confirmedWithoutImage = 0,
                readyToConfirm = 0,
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

    override suspend fun pause(publicId: String): Result<RecurringItem> =
        Result.failure(IllegalArgumentException("not used"))

    override suspend fun resume(publicId: String): Result<RecurringItem> =
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
