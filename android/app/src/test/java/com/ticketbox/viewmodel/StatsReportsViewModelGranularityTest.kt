package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
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
import kotlin.test.assertNull
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

    @Test
    fun reportRefreshAndExportKeepCapturedCurrencyAndAllFilters() = reportsTest { repo ->
        repo.overviewResult = Result.success(overview("2026-06").copy(homeCurrencyCode = "JPY"))
        val vm = StatsReportsViewModel(repo)
        vm.refresh("2026-06", "")
        advanceUntilIdle()
        vm.setGranularity(ReportGranularity.Month)
        advanceUntilIdle()
        vm.setMerchantCategory("餐饮")
        advanceUntilIdle()
        vm.exportReport()
        advanceUntilIdle()
        val exported = repo.exportQueries.single()
        assertEquals("2026-06", exported.month)
        assertEquals("JPY", exported.homeCurrencyCode)
        assertEquals("餐饮", exported.merchantCategory)
        assertEquals(ReportGranularity.Month, exported.granularity)
        assertEquals(repo.access.value?.binding, repo.exportBindings.single())
    }

    @Test
    fun replacementBindingClearsPreparedExportAndDoesNotShowLateOldReport() = reportsTest { repo ->
        repo.overviewResult = Result.success(overview("2026-06"))
        val vm = StatsReportsViewModel(repo)
        vm.refresh("2026-06", "")
        advanceUntilIdle()
        vm.exportReport()
        advanceUntilIdle()
        val oldBinding = requireNotNull(repo.access.value).binding
        val gate = CompletableDeferred<Result<ReportsOverview>>()
        repo.overviewResponder = { gate.await() }
        vm.refresh("2026-06", "")
        runCurrent()
        repo.access.value = null
        runCurrent()
        gate.complete(Result.success(overview("2026-06")))
        advanceUntilIdle()
        assertNull(vm.uiState.value.reportsOverview)
        assertNull(vm.takeExport(oldBinding))
    }

    @Test fun lateExportFromOldMonthCannotOverwriteTheNewMonthExport() = reportsTest { repo ->
        repo.overviewResult = Result.success(overview("2026-06"))
        val first = CompletableDeferred<Result<CsvExport>>()
        val second = CompletableDeferred<Result<CsvExport>>()
        repo.exportResponder = { query -> if (query.month == "2026-06") first.await() else second.await() }
        val vm = StatsReportsViewModel(repo)
        vm.refresh("2026-06", "")
        advanceUntilIdle()
        vm.exportReport()
        runCurrent()
        repo.overviewResult = Result.success(overview("2026-05"))
        vm.refresh("2026-05", "")
        runCurrent()
        vm.exportReport()
        runCurrent()
        second.complete(Result.success(CsvExport("may.csv", byteArrayOf(5))))
        runCurrent()
        val originalId = vm.uiState.value.exportId
        first.complete(Result.success(CsvExport("june.csv", byteArrayOf(6))))
        advanceUntilIdle()
        assertEquals("may.csv", vm.uiState.value.exportFile?.fileName)
        assertEquals(originalId, vm.uiState.value.exportId)
    }

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
    fun refreshQueriesWithDefaultGranularityAndMerchantMetric() = reportsTest { repo ->
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(listOf(ReportGranularity.Day), repo.overviewQueries.map { it.granularity })
        assertEquals(listOf(ReportRankingMetric.Count), repo.overviewQueries.map { it.rankingMetric })

        vm.setRankingMetric(ReportRankingMetric.Amount)
        advanceUntilIdle()

        assertEquals(
            listOf(ReportRankingMetric.Count, ReportRankingMetric.Amount),
            repo.overviewQueries.map { it.rankingMetric },
        )
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
    fun refreshNeverRequestsRetiredDashboardCards() = reportsTest { repo ->
        val vm = StatsReportsViewModel(repo)

        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        vm.refresh(month = "2026-06", selectedTag = "coffee")
        advanceUntilIdle()

        assertEquals(0, repo.dashboardCardCalls)
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
        assertEquals(ReportGoalsLoadState.Loading, vm.uiState.value.reportGoalsLoadState)

        goalsGate.complete(Result.success(emptyList()))
        advanceUntilIdle()
        assertFalse(vm.uiState.value.reportsLoading)
        assertEquals(ReportGoalsLoadState.Loaded, vm.uiState.value.reportGoalsLoadState)
    }

    @Test
    fun goalsFailureDoesNotMasqueradeAsEmptyGoalSet() = reportsTest { repo ->
        repo.overviewResult = Result.success(overview(month = "2026-06"))
        repo.goalsResponder = { Result.failure(RuntimeException("goals unavailable")) }
        val vm = StatsReportsViewModel(repo)

        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        assertEquals(emptyList(), vm.uiState.value.reportGoals)
        assertEquals(ReportGoalsLoadState.Failed, vm.uiState.value.reportGoalsLoadState)
        assertNull(vm.uiState.value.reportsMessage)
    }

    @Test
    fun changedMonthClearsGoalsFromPreviousReportWhileLoadingAndOnFailure() = reportsTest { repo ->
        val trustedGoal = goal("goal-trusted")
        repo.overviewResult = Result.success(overview(month = "2026-06"))
        repo.goalsResponder = { Result.success(listOf(trustedGoal)) }
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()

        val goalsGate = CompletableDeferred<Result<List<Goal>>>()
        repo.goalsResponder = { goalsGate.await() }
        vm.refresh(month = "2026-05", selectedTag = "")
        runCurrent()

        assertEquals(emptyList(), vm.uiState.value.reportGoals)
        assertEquals(ReportGoalsLoadState.Loading, vm.uiState.value.reportGoalsLoadState)

        goalsGate.complete(Result.failure(RuntimeException("goals unavailable")))
        advanceUntilIdle()
        assertEquals(emptyList(), vm.uiState.value.reportGoals)
        assertEquals(ReportGoalsLoadState.Failed, vm.uiState.value.reportGoalsLoadState)
    }

    @Test
    fun duplicateReportRefreshForSameScopeIsCoalescedWhileInFlight() = reportsTest { repo ->
        val overviewGate = CompletableDeferred<Result<ReportsOverview>>()
        repo.overviewResponder = { overviewGate.await() }
        val vm = StatsReportsViewModel(repo)

        vm.refresh(month = "2026-06", selectedTag = "")
        runCurrent()
        assertEquals(1, repo.overviewQueries.size)

        vm.refresh(month = "2026-06", selectedTag = "")
        runCurrent()
        assertEquals(1, repo.overviewQueries.size)

        overviewGate.complete(Result.success(overview(month = "2026-06")))
        advanceUntilIdle()
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(2, repo.overviewQueries.size)
    }

    @Test
    fun tagFilterClearsReportSliceWithoutQueryingUntaggedOverview() = reportsTest { repo ->
        repo.overviewResult = Result.success(overview(month = "2026-06"))
        val vm = StatsReportsViewModel(repo)
        vm.refresh(month = "2026-06", selectedTag = "")
        advanceUntilIdle()
        assertEquals(1, repo.overviewQueries.size)
        assertEquals("2026-06", vm.uiState.value.reportsOverview?.month)

        vm.refresh(month = "2026-06", selectedTag = "coffee")
        advanceUntilIdle()

        assertEquals(1, repo.overviewQueries.size)
        assertEquals(0, repo.dashboardCardCalls)
        assertNull(vm.uiState.value.reportsOverview)
        assertFalse(vm.uiState.value.reportsLoading)
        assertNull(vm.uiState.value.reportsMessage)
    }
    @Test
    fun goalSnapshotSourceReachesTheRealOverviewAndClearsOnQueryRefusal() = reportsTest { repo ->
        repo.goalsFromCache = true
        repo.goalsResponder = { Result.success(listOf(goal("cached"))) }
        val vm = StatsReportsViewModel(repo)
        vm.refresh("2026-06", "")
        advanceUntilIdle()
        val monthly = MonthlyStatsUiState(month = "2026-06", binding = repo.access.value?.binding)
        val shown = mergeStatsUiState(monthly, StatsBudgetUiState(), vm.uiState.value)
        assertEquals(listOf("cached"), shown.reportGoals.map { it.publicId })
        assertEquals("2026-09-09T00:00:00Z", shown.reportGoalsFetchedAt)
        assertEquals(true, shown.reportGoalsFromCache)
        repo.goalsResponder = { Result.failure(com.ticketbox.data.repository.RepositoryException(
            "Forbidden", httpStatusCode = 403)) }
        vm.refresh("2026-06", "")
        advanceUntilIdle()
        val refused = mergeStatsUiState(monthly, StatsBudgetUiState(), vm.uiState.value)
        assertEquals(emptyList(), refused.reportGoals)
        assertNull(refused.reportGoalsFetchedAt)
        assertEquals(ReportGoalsLoadState.Failed, refused.reportGoalsLoadState)
    }

}

// Top-level (not nested) so the detekt TooManyFunctions baseline entry matches —
// it must implement the full ReportsActions surface (13 functions) for the VM under test.
private class RecordingReportsActions : ReportsActions {
    val access = kotlinx.coroutines.flow.MutableStateFlow<com.ticketbox.data.repository.LedgerAccessContext?>(
        com.ticketbox.data.repository.LedgerAccessContext(com.ticketbox.data.repository.LogicalSessionBinding(
            "https://reports.test", "ledger-1", "owner-1", "session-1", "revision-1"), true))
    var exportResponder: (suspend (ReportsOverviewQuery) -> Result<CsvExport>)? = null
    val exportQueries = mutableListOf<ReportsOverviewQuery>()
    val exportBindings = mutableListOf<com.ticketbox.data.repository.LogicalSessionBinding?>()
    override fun observeReportsAccess() = access
    val overviewQueries = mutableListOf<ReportsOverviewQuery>()
    var overviewResult: Result<ReportsOverview> = Result.failure(RuntimeException("overview unavailable in this fake"))
    var overviewResponder: (suspend () -> Result<ReportsOverview>)? = null
    var goalsFromCache = false
    var goalsResponder: (suspend () -> Result<List<Goal>>)? = null
    var dashboardCardCalls = 0

    override fun canModifyLedger(): Boolean = true

    override suspend fun reportsOverview(query: ReportsOverviewQuery, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?): Result<ReportsOverview> {
        overviewQueries += query
        overviewResponder?.let { return it() }
        return overviewResult.map { it.copy(month = query.month ?: it.month, granularity = query.granularity,
            rankingMetric = query.rankingMetric, merchantCategory = query.merchantCategory) }
    }

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?): Result<CsvExport> {
        exportQueries += query
        exportBindings += expectedBinding
        return exportResponder?.invoke(query) ?: Result.success(CsvExport("report.csv", "report".toByteArray()))
    }

    override suspend fun goals(month: String?, includeArchived: Boolean, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> =
        (goalsResponder?.invoke() ?: Result.success(emptyList())).map { ReadSnapshot(it, "2026-09-09T00:00:00Z", goalsFromCache) }

    override suspend fun createDebtGoal(name: String, debtPublicIds: List<String>, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun goal(publicId: String, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<Goal>> =
        Result.failure(UnsupportedOperationException())

    override suspend fun archiveGoal(publicId: String, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun debtGoals(includeArchived: Boolean, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> =
        Result.success(ReadSnapshot(emptyList(), "2026-09-09T00:00:00Z", false))

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

    override fun dashboardAccess() = access.value

    override suspend fun dashboardCards(
        binding: com.ticketbox.data.repository.LogicalSessionBinding,
        surface: DashboardSurface,
    ): Result<DashboardCards> =
        Result.success(DashboardCards(surface = surface, items = emptyList())).also { dashboardCardCalls++ }

    override suspend fun updateDashboardCards(
        binding: com.ticketbox.data.repository.LogicalSessionBinding,
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
    homeCurrencyCode = "CNY",
)

private fun goal(publicId: String) = Goal(
    publicId = publicId,
    ledgerId = "ledger-1",
    name = "本月餐饮",
    goalType = "spending_limit",
    period = "monthly",
    month = "2026-06",
    category = "餐饮",
    targetAmountCents = 10_000L,
    spentAmountCents = 2_500L,
    remainingAmountCents = 7_500L,
    progressPercent = 25,
    progressState = GoalProgressState.OnTrack,
    status = "active",
    createdAt = "2026-06-01T00:00:00Z",
    updatedAt = "2026-06-02T00:00:00Z",
    rowVersion = 1L,
    archivedAt = null,
)
