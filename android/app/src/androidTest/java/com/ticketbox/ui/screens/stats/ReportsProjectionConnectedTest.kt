package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ReportsProjectionConnectedTest {
    @get:Rule val compose = createComposeRule()

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
        compose.onNodeWithTag("reports-export").performScrollTo().performClick()
        assertEquals(1, exports)
        compose.onNode(hasText(formatDisplayAmount(1200, CurrencyDisplay.forRecord("JPY")), substring = true))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
    }
}
