package com.ticketbox.ui.screens

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanBudgetSection
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BudgetUiState
import org.junit.Rule
import org.junit.Test

class PlanBudgetCurrencyTest {
    @get:Rule val composeRule = createComposeRule()

    @Test
    fun planOverviewKeepsBudgetYenUnderDifferentDisplayDefault() {
        showBudget(recordedBudget())
        composeRule.onNodeWithText("¥1,200").assertIsDisplayed()
        composeRule.onNodeWithText("¥12.00").assertDoesNotExist()
    }

    @Test
    fun planOverviewExplainsMissingConversionWithoutInventingProgress() {
        showBudget(recordedBudget().copy(spentAmountCents = null, remainingAmountCents = null,
            overspentAmountCents = null, missingCurrencyCodes = listOf("USD")))
        composeRule.onNodeWithText("缺少 USD 的汇率，部分金额暂无法汇总。").assertIsDisplayed()
        composeRule.onNodeWithText("0%", substring = true).assertDoesNotExist()
    }

    private fun showBudget(budget: BudgetMonthly) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                    PlanBudgetSection(BudgetUiState(budget = budget), PlanBudgetNavigationActions({}, {}))
                }
            }
        }
    }

    private fun recordedBudget() = BudgetMonthly(
        ledgerId = "owner", month = "2026-09", configured = true, homeCurrencyCode = "JPY", rowVersion = 1,
        totalAmountCents = 2400, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
        flexBudgetCents = 2400, spentAmountCents = 1200, excludedAmountCents = 0,
        remainingAmountCents = 1200, overspentAmountCents = 0, excludedCategories = emptyList(),
        excludedBreakdown = emptyList(), categoryBudgets = emptyList(), updatedAt = null)
}
