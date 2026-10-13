package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.ForcedSize
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.screens.StatsFilterActions
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.ui.screens.StatsScreenActions
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DashboardLayoutUiState
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.viewmodel.StatsFilterOptionsLoadState
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ReportsProjectionConnectedTest {
    @get:Rule val compose = createComposeRule()

    @Test fun reportTaskKeepsMonthAndQueryActionsAcrossWindowChanges() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val viewport = mutableStateOf(393.dp)
        val scale = mutableStateOf(1f)
        val skin = mutableStateOf(AppSkin.Paper)
        val report = populatedReport()
        var granularity: ReportGranularity? = null
        var ranking: ReportRankingMetric? = null
        var category: String? = null
        var exports = 0
        compose.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(viewport.value, 900.dp))) {
                CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale.value)) {
                    TicketboxTheme(skin = skin.value) {
                        StatsScreen(
                            state = StatsUiState(month = report.month, reportsOverview = report,
                                stats = MonthlyStats(homeCurrencyCode = "CNY", month = report.month,
                                    totalAmountCents = report.totalAmountCents, count = report.count, byCategory = emptyList()),
                                statsSource = StatsSource.Backend, months = listOf(report.month),
                                monthsLoadState = StatsFilterOptionsLoadState.Loaded,
                                tagsLoadState = StatsFilterOptionsLoadState.Loaded),
                            overview = OverviewModulesState(DashboardLayoutUiState(cards = emptyList(), canModify = false), RecurringUiState()),
                            actions = StatsScreenActions(
                                filters = StatsFilterActions({}, {}), onRefresh = {}, onOpenDataQuality = {},
                                reports = StatsReportActions({}, { granularity = it }, { ranking = it },
                                    onMerchantCategoryChange = { category = it }, onExport = { exports += 1 }),
                                overview = OverviewInteractionActions(DashboardLayoutActions({}, {}, { _, _ -> }, { _, _ -> }, {}, {}, {}),
                                    OverviewModuleActions({}, {}, {}, {})),
                            ),
                        )
                    }
                }
            }
        }
        compose.onNode(hasText(context.getString(R.string.stats_tab_trend)) and hasClickAction()).performClick()
        capture("reports-paper")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.stats_reports_granularity_week)))
        compose.onNodeWithText(context.getString(R.string.stats_reports_granularity_week)).performClick()
        assertEquals(ReportGranularity.Week, granularity)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.reports_rankings_title)))
        compose.onNodeWithText(context.getString(R.string.reports_rankings_title)).performClick()
        compose.onNodeWithTag("reports-category-filter").performClick()
        compose.onNode(hasText("餐饮") and hasClickAction()).performClick()
        assertEquals("餐饮", category)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.stats_reports_merchant_metric_amount)))
        compose.onNodeWithText(context.getString(R.string.stats_reports_merchant_metric_amount)).performClick()
        assertEquals(ReportRankingMetric.Amount, ranking)
        capture("reports-rankings")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.reports_rankings_title)))
        compose.onNodeWithText(context.getString(R.string.reports_rankings_title)).performClick()
        compose.runOnIdle { viewport.value = 768.dp }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("reports-data"))
        compose.onNodeWithTag("reports-data").performClick()
        compose.onNodeWithTag("reports-export").performClick()
        assertEquals(1, exports)
        captureSheet("reports-data")
        compose.onNodeWithText(context.getString(R.string.reports_return_chart)).performClick()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("reports-total"))
        capture("reports-wide")
        compose.runOnIdle { viewport.value = 320.dp; scale.value = 2f; skin.value = AppSkin.Midnight }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("reports-total"))
        compose.onNodeWithTag("reports-total").assertIsDisplayed()
        capture("reports-midnight-large")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.reports_comparisons_title)))
        compose.onNodeWithText(context.getString(R.string.reports_comparisons_title)).performClick()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.stats_reports_answer_yoy_label)))
        capture("reports-comparison-midnight-large")
    }

    private fun capture(name: String) = saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())

    private fun captureSheet(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    @Test fun signedJpyNetExpenseKeepsItsFullAmountInSummaryTrendAndReadableData() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val report = populatedReport().copy(homeCurrencyCode = "JPY", totalAmountCents = -500, count = 2,
            trend = listOf(ReportTrendPoint("2026-09-01", "9/1", 500, 1), ReportTrendPoint("2026-09-02", "9/2", -1000, 1)))
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            ReportsInsightCard(report, modifier = Modifier.verticalScroll(rememberScrollState()),
                actions = StatsReportActions({}, {}, {}))
        } }
        val currency = CurrencyDisplay.forRecord("JPY")
        compose.onNodeWithTag("reports-total").assertTextEquals(formatDisplayAmount(-500, currency))
        compose.onNodeWithText(formatDisplayAmount(-1000, currency)).performScrollTo().assertIsDisplayed()
        capture("reports-signed-jpy")
        compose.onNodeWithTag("reports-data").performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.reports_data_title)).performScrollTo().assertIsDisplayed()
        captureSheet("reports-signed-data-header")
        compose.onNode(hasText(formatDisplayAmount(-1000, currency)) and hasAnyAncestor(hasTestTag("reports-data-sheet")))
            .performScrollTo().assertIsDisplayed()
        compose.onNode(hasText(context.getString(R.string.reports_scope, "2026年9月", "JPY"))
            and hasAnyAncestor(hasTestTag("reports-data-sheet"))).assertIsDisplayed()
        captureSheet("reports-signed-data")
        compose.onNode(hasText(formatDisplayAmount(-500, currency)) and hasAnyAncestor(hasTestTag("reports-data-sheet")))
            .performScrollTo().assertIsDisplayed()
        captureSheet("reports-signed-data-total")
    }

    private fun populatedReport() = ReportsOverview(
        month = "2026-09", timezone = "Asia/Shanghai", granularity = ReportGranularity.Day,
        totalAmountCents = 246000, count = 12, previousMonth = "2026-08", previousTotalAmountCents = 274000,
        previousCount = 14, yearOverYearMonth = "2025-09", yearOverYearTotalAmountCents = 230000,
        yearOverYearCount = 11, yearOverYearDeltaAmountCents = 16000, yearOverYearDeltaCount = 1,
        merchantCategory = null, rankingMetric = ReportRankingMetric.Count,
        trend = listOf(32000L, 28500L, 30600L, 29100L, 27400L, 98400L).mapIndexed { index, amount ->
            val day = 1 + index * 5
            ReportTrendPoint("2026-09-${day.toString().padStart(2, '0')}", "9/$day", amount, 2)
        },
        merchantRanking = listOf(ReportMerchantRanking("日常采购", 132000, 8), ReportMerchantRanking("住所", 114000, 4)),
        categoryComparison = listOf("居住" to 114000L, "餐饮" to 60000L, "购物" to 48000L, "交通" to 24000L).map { (name, amount) ->
            ReportCategoryComparison(name, amount, 3, amount + 7000, 4, -7000, -1, amount - 4000, 3, 4000, 0)
        }, homeCurrencyCode = "CNY",
    )

    @Test fun incompleteJpyReportRetainsKnownCategoryAmountsAndOpensTheExactHistoricalGap() {
        val gap = CurrencyProjectionGap("CNY", "JPY", "2025-09-07")
        val report = ReportsOverview(month = "2026-09", timezone = "Asia/Tokyo", granularity = ReportGranularity.Day,
            totalAmountCents = null, count = 4, previousMonth = "2026-08", previousTotalAmountCents = null,
            previousCount = 2, yearOverYearMonth = "2025-09", yearOverYearTotalAmountCents = null,
            yearOverYearCount = 1, yearOverYearDeltaAmountCents = null, yearOverYearDeltaCount = 3,
            merchantCategory = null, rankingMetric = ReportRankingMetric.Count,
            trend = listOf(ReportTrendPoint("2026-09-01", "9/1", null, 4)), merchantRanking = emptyList(),
            categoryComparison = listOf(ReportCategoryComparison("Known category", 1200, 2, null, 1, null, 1, null, 1, null, 1)),
            homeCurrencyCode = "JPY", missingRates = listOf(gap))
        var selected: CurrencyProjectionGap? = null
        var exports = 0
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay.Base) {
                ReportsInsightCard(report, modifier = Modifier.verticalScroll(rememberScrollState()),
                    actions = StatsReportActions(onDrillToLedger = {}, onGranularityChange = {}, onRankingMetricChange = {},
                        onRepairRates = { selected = it }, onExport = { exports += 1 }))
            }
        } }
        compose.onNodeWithTag("report-rate-CNY-2025-09-07").performScrollTo().performClick()
        assertEquals(gap, selected)
        compose.onNodeWithTag("reports-data").performScrollTo().performClick()
        compose.onNodeWithTag("reports-export").performClick()
        assertEquals(1, exports)
        compose.onNodeWithText(InstrumentationRegistry.getInstrumentation().targetContext.getString(R.string.reports_return_chart)).performClick()
        compose.onNodeWithText(InstrumentationRegistry.getInstrumentation().targetContext.getString(R.string.reports_rankings_title))
            .performScrollTo().performClick()
        compose.onNode(hasText(formatDisplayAmount(1200, CurrencyDisplay.forRecord("JPY")), substring = true))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
    }
}
