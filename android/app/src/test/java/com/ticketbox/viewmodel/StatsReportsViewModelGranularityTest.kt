package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import kotlinx.coroutines.CompletableDeferred
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/**
 * 轴3 粒度切换:[StatsReportsViewModel] 是粒度唯一持有方——refresh 用当前粒度、
 * setGranularity 置新值并按当前月重拉、同值切换不重复打 API。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class StatsReportsViewModelGranularityTest {

    private fun reportsTest(block: suspend TestScope.(RecordingReportsActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(RecordingReportsActions())
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshQueriesWithDayGranularityByDefault() = reportsTest { repo ->
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(listOf(ReportGranularity.Day), repo.overviewQueries.map { it.granularity })
        assertEquals(listOf(ReportRankingMetric.Count), repo.overviewQueries.map { it.rankingMetric })
    }

    @Test
    fun setGranularityRefetchesCurrentMonthWithNewGranularity() = reportsTest { repo ->
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        vm.setGranularity(ReportGranularity.Week)
        advanceUntilIdle()

        assertEquals(
            listOf(ReportGranularity.Day, ReportGranularity.Week),
            repo.overviewQueries.map { it.granularity },
        )
        assertEquals("2026-06", repo.overviewQueries.last().month)
        // 后续 refresh 保持已选粒度(粒度是 VM 持久选择,不随月份切换回弹)。
        vm.refresh(month = "2026-05", selectedTag = "")
        advanceUntilIdle()
        assertEquals(ReportGranularity.Week, repo.overviewQueries.last().granularity)
    }

    @Test
    fun settingSameGranularityDoesNotRefetch() = reportsTest { repo ->
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        vm.setGranularity(ReportGranularity.Day)
        advanceUntilIdle()

        assertEquals(1, repo.overviewQueries.size)
    }

    @Test
    fun overviewStopsReportsLoadingBeforeGoalsComplete() = reportsTest { repo ->
        val goalsGate = CompletableDeferred<Result<List<Goal>>>()
        repo.overviewResult = Result.success(overview(month = "2026-06"))
        repo.goalsResponder = { goalsGate.await() }
        val vm = StatsReportsViewModel(repo)

        vm.refresh(month = "2026-06", selectedTag = "")
        runCurrent()

        assertFalse(vm.uiState.value.reportsLoading)
        assertEquals("2026-06", vm.uiState.value.reportsOverview?.month)
        assertEquals(emptyList(), vm.uiState.value.reportGoals)

        goalsGate.complete(Result.success(emptyList()))
        advanceUntilIdle()
        assertFalse(vm.uiState.value.reportsLoading)
    }
}

// Top-level (not nested) so the detekt TooManyFunctions baseline entry matches —
// it must implement the full ReportsActions surface (13 functions) for the VM under test.
private class RecordingReportsActions : ReportsActions {
    val overviewQueries = mutableListOf<ReportsOverviewQuery>()
    var overviewResult: Result<ReportsOverview> = Result.failure(RuntimeException("overview unavailable in this fake"))
    var goalsResponder: (suspend () -> Result<List<Goal>>)? = null

    override fun canModifyLedger(): Boolean = true

    override suspend fun reportsOverview(query: ReportsOverviewQuery): Result<ReportsOverview> {
        overviewQueries += query
        return overviewResult
    }

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery): Result<CsvExport> =
        Result.failure(UnsupportedOperationException())

    override suspend fun goals(month: String?, includeArchived: Boolean): Result<List<Goal>> =
        goalsResponder?.invoke() ?: Result.success(emptyList())

    override suspend fun createGoal(draft: GoalDraft): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun createDebtGoal(name: String, debtPublicIds: List<String>): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun goal(publicId: String): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun archiveGoal(publicId: String): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun debtGoals(includeArchived: Boolean): Result<List<Goal>> =
        Result.success(emptyList())

    override suspend fun replaceDebtLinks(
        publicId: String,
        expectedRowVersion: Long,
        debtPublicIds: List<String>,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun acknowledgeDebtIntegrityReview(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun setDebtGoalTargetDate(
        publicId: String,
        expectedRowVersion: Long,
        targetDate: String?,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        Result.success(DashboardCards(surface = surface, items = emptyList()))

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> = Result.failure(UnsupportedOperationException())
}

private fun overview(month: String) = ReportsOverview(
    month = month,
    timezone = "Asia/Shanghai",
    granularity = ReportGranularity.Day,
    totalAmountCents = 1200L,
    count = 1,
    previousMonth = "2026-05",
    previousTotalAmountCents = 0L,
    previousCount = 0,
    yearOverYearMonth = "2025-06",
    yearOverYearTotalAmountCents = 0L,
    yearOverYearCount = 0,
    yearOverYearDeltaAmountCents = 1200L,
    yearOverYearDeltaCount = 1,
    merchantCategory = null,
    rankingMetric = ReportRankingMetric.Count,
    trend = listOf(ReportTrendPoint(bucket = "$month-01", label = "1日", amountCents = 1200L, count = 1)),
    merchantRanking = emptyList(),
    categoryComparison = emptyList(),
)
