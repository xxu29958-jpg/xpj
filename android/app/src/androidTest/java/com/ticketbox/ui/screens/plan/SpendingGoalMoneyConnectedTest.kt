package com.ticketbox.ui.screens.plan

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.stats.GoalsSummaryCard
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ReportGoalsLoadState
import org.junit.Rule
import org.junit.Test

class SpendingGoalMoneyConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val goal = Goal(
        publicId = "captured-jpy", ledgerId = "test-ledger", name = "旅行限额", goalType = "spending_limit",
        period = "monthly", month = "2026-09", category = null, targetAmountCents = 1200,
        spentAmountCents = null, remainingAmountCents = null, progressPercent = null,
        progressState = GoalProgressState.Unavailable, status = "active", createdAt = "", updatedAt = "",
        rowVersion = 1, archivedAt = null, homeCurrencyCode = "JPY",
    )

    @Test fun listUsesCapturedJpyAndShowsUnavailableProgressUnderCnyDisplay() {
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                    SpendingGoalListCard(listOf(goal), {})
                }
            }
        }
        compose.onNodeWithText("JPY ¥1,200").assertExists()
        compose.onNodeWithText(context.getString(R.string.spending_goal_progress_unavailable)).assertExists()
        compose.onNodeWithContentDescription(context.getString(R.string.spending_goal_progress_a11y, goal.name, 0))
            .assertDoesNotExist()
    }

    @Test fun detailKeepsOriginalUnitsWhenCurrencyWasNeverCaptured() {
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                SpendingGoalViewContent(goal.copy(homeCurrencyCode = null), canModify = false, onArchive = {})
            }
        }
        compose.onNodeWithText(context.getString(R.string.spending_goal_original_amount_unknown, 1200)).assertExists()
        compose.onNodeWithText("CNY ¥12.00").assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.spending_goal_progress_unavailable)).assertExists()
    }

    @Test fun statisticsDoesNotDescribeMissingConversionAsZeroOrStable() {
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                GoalsSummaryCard(listOf(goal), ReportGoalsLoadState.Loaded)
            }
        }
        compose.onNodeWithText("JPY ¥1,200").assertExists()
        compose.onNodeWithText(context.getString(R.string.stats_reports_goals_stable)).assertDoesNotExist()
        compose.onAllNodesWithText(context.getString(R.string.stats_reports_goal_percent, 0)).assertCountEquals(0)
        compose.onNodeWithText(context.getString(R.string.spending_goal_progress_unavailable)).assertExists()
    }
}
