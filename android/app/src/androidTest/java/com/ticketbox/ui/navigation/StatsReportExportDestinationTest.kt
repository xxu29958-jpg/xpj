package com.ticketbox.ui.navigation

import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.core.app.ActivityOptionsCompat
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.ui.screens.stats.ReportsInsightCard
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.exportReport
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.flowOf
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.lang.reflect.Proxy

class StatsReportExportDestinationTest {
    @get:Rule val compose = createComposeRule()

    @Test fun completedExportOpensTheSaveDestinationOnceAfterAdmissionHadNoFile() {
        val response = CompletableDeferred<Result<CsvExport>>()
        val repo = exportActions(response)
        val vm = StatsReportsViewModel(repo)
        val launches = mutableListOf<String>()
        val registry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>, input: I,
                options: ActivityOptionsCompat?) { launches += input.toString() }
        }
        val owner = object : ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides owner) {
                val state by vm.uiState.collectAsState()
                StatsReportExportDestination(vm, state)
                state.reportsOverview?.let { ReportsInsightCard(it,
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    actions = StatsReportActions(onDrillToLedger = {}, onGranularityChange = vm::setGranularity,
                        onRankingMetricChange = vm::setRankingMetric, onMerchantCategoryChange = vm::setMerchantCategory,
                        onExport = vm::exportReport),
                    exporting = state.exporting) }
            }
        } }
        compose.runOnIdle { vm.refresh("2026-09", "") }
        compose.waitUntil(5_000) { vm.uiState.value.reportsOverview != null }
        compose.onNodeWithTag("reports-export").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(true, vm.uiState.value.exportId != null)
            assertEquals(null, vm.uiState.value.exportFile)
            assertEquals(emptyList<String>(), launches)
            response.complete(Result.success(CsvExport("original-jpy-report.csv", "report".toByteArray())))
        }
        compose.waitUntil(5_000) { launches.size == 1 }
        compose.waitForIdle()
        assertEquals(listOf("original-jpy-report.csv"), launches)
        assertEquals(true, vm.uiState.value.exportDestinationPending)
    }
}

private fun exportActions(response: CompletableDeferred<Result<CsvExport>>): ReportsActions {
    val unused = Proxy.newProxyInstance(ReportsActions::class.java.classLoader, arrayOf(ReportsActions::class.java)) {
        _, method, _ -> error("Unexpected reports action: ${method.name}")
    } as ReportsActions
    val access = LedgerAccessContext(LogicalSessionBinding("https://reports.test", "ledger", "owner", "session", "revision"), true)
    val report = ReportsOverview("2026-09", "UTC", ReportGranularity.Day, 1200, 1, "2026-08", 0, 0,
        "2025-09", 0, 0, 1200, 1, null, ReportRankingMetric.Count, emptyList(), emptyList(), emptyList(), "JPY")
    return object : ReportsActions by unused {
        override fun dashboardAccess() = access
        override fun observeReportsAccess() = flowOf(access)
        override suspend fun reportsOverview(query: ReportsOverviewQuery, expectedBinding: LogicalSessionBinding?) = Result.success(report)
        override suspend fun goals(month: String?, includeArchived: Boolean, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> = Result.success(ReadSnapshot(emptyList(), "2026-09-09T00:00:00Z", false))
        override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery, expectedBinding: LogicalSessionBinding?) = response.await()
    }
}
