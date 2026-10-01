package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MONEY_MINOR_MAX
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.budget.BudgetSummarySection
import com.ticketbox.ui.screens.recurring.RecurringHeroModel
import com.ticketbox.ui.screens.recurring.RecurringHeroSection
import com.ticketbox.ui.screens.stats.StatsOverviewCard
import com.ticketbox.ui.screens.stats.StatsOverviewHeaderModel
import com.ticketbox.ui.screens.stats.ReportsAnswerHeader
import com.ticketbox.ui.screens.stats.ReportsAnswerModel
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.StatsSource
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AmountSummaryConsumersTest {
    @get:Rule val compose = createComposeRule()
    private val currency = CurrencyDisplay.forRecord("CNY")
    private val maximum = formatDisplayAmount(MONEY_MINOR_MAX, currency)

    @Test fun recurringSingleCurrencyTotalKeepsItsCurrencyAndAllDigits() = verify(
        "recurring-total", listOf("CNY $maximum"),
    ) {
        RecurringHeroSection(RecurringHeroModel(true, mapOf("CNY" to MONEY_MINOR_MAX), 1, null))
    }

    @Test fun recurringMixedCurrenciesKeepBothExactTotals() = verify(
        "recurring-currencies", listOf("CNY $maximum", "JPY ${formatDisplayAmount(MONEY_MINOR_MAX, CurrencyDisplay.forRecord("JPY"))}"),
    ) {
        RecurringHeroSection(RecurringHeroModel(true, mapOf("CNY" to MONEY_MINOR_MAX, "JPY" to MONEY_MINOR_MAX), 2, null))
    }

    @Test fun overviewKeepsMonthlyAndRecentAmountsReadable() = verify(
        "insights-totals", listOf(maximum, formatDisplayAmount(MONEY_MINOR_MAX - 100, currency),
            "比上月多 ${formatDisplayAmount(MONEY_MINOR_MAX - 100, currency)}"),
    ) {
        StatsOverviewCard(StatsOverviewHeaderModel(
            stats = MonthlyStats("CNY", month = "2026-10", totalAmountCents = MONEY_MINOR_MAX, count = 2, byCategory = emptyList()),
            statsSource = StatsSource.Backend,
            recent7DaysAmountCents = MONEY_MINOR_MAX - 100,
            comparison = MonthComparison("2026-10", "2026-09", MONEY_MINOR_MAX, 100, MONEY_MINOR_MAX - 100, null),
            comparisonHomeCurrencyCode = "CNY",
        ))
    }

    @Test fun budgetKeepsRemainingAndItsComponentAmountsReadable() = verify(
        "budget-totals", listOf(maximum, formatDisplayAmount(MONEY_MINOR_MAX - 100, currency)),
    ) {
        BudgetSummarySection(
            budget = BudgetMonthly(
                ledgerId = "amount-reading", month = "2026-10", configured = true,
                totalAmountCents = MONEY_MINOR_MAX, rolloverAmountCents = 0, fixedAmountCents = 0,
                nonMonthlyAmountCents = 0, flexBudgetCents = MONEY_MINOR_MAX,
                spentAmountCents = 100, excludedAmountCents = 0, remainingAmountCents = MONEY_MINOR_MAX - 100,
                overspentAmountCents = 0, excludedCategories = emptyList(), excludedBreakdown = emptyList(),
                categoryBudgets = emptyList(), updatedAt = "2026-10-01T00:00:00Z", homeCurrencyCode = "CNY",
            ),
            loading = false, loadError = null, currencyDisplay = currency, onRetry = {},
        )
    }

    @Test fun reportKeepsItsHeadingTotalAndSignedComparisonsReadable() = verify(
        "report-summary", listOf("本月结论", maximum, "多 ${formatDisplayAmount(MONEY_MINOR_MAX - 1, currency)}", "少 $maximum"),
    ) {
        ReportsAnswerHeader(ReportsAnswerModel(
            month = "2026-10", granularity = ReportGranularity.Month, totalAmountCents = MONEY_MINOR_MAX, count = 2,
            previousMonth = "2026-09", hasPreviousMonthComparison = true, previousTotalAmountCents = 1,
            monthDeltaAmountCents = MONEY_MINOR_MAX - 1, monthDeltaPercent = null,
            yearOverYearMonth = "2025-10", hasYearOverYearComparison = true, yearOverYearDeltaAmountCents = -MONEY_MINOR_MAX,
            trendPoints = emptyList(), trendEvidence = null, homeCurrencyCode = "CNY",
        ))
    }

    private fun verify(name: String, amounts: List<String>, content: @Composable () -> Unit) {
        val skin = mutableStateOf(AppSkin.Paper)
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, 1.8f)) {
                TicketboxTheme(skin = skin.value) {
                    Box(Modifier.width(328.dp).verticalScroll(rememberScrollState())) { content() }
                }
            }
        }
        for (theme in listOf(AppSkin.Paper, AppSkin.Midnight)) {
            compose.runOnIdle { skin.value = theme }
            saveConsumerArtPreview("$name-${theme.name}-large-font", compose.onRoot().captureToImage().asAndroidBitmap())
            for (amount in amounts) {
                val nodes = compose.onAllNodesWithText(amount, useUnmergedTree = true)
                val count = nodes.fetchSemanticsNodes().size
                assertTrue("$name must retain $amount", count > 0)
                repeat(count) { index ->
                    val results = mutableListOf<TextLayoutResult>()
                    nodes[index].performScrollTo()
                        .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(results) }
                    assertTrue("$name must lay out $amount", results.isNotEmpty())
                    assertTrue("$name must show every digit and currency of $amount at large font", results.all { result ->
                        !result.hasVisualOverflow && (0 until result.lineCount).none(result::isLineEllipsized)
                    })
                }
            }
        }
    }
}
