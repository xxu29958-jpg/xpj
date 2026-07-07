package com.ticketbox.ui.screens

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.stats.StatsPlanningActions
import com.ticketbox.ui.screens.stats.StatsPlanningMenuTestTags
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.StatsUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class StatsPlanningMenuTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun planningMenuAnnouncesStateKeepsTouchTargetAndDispatchesActions() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val menuDescription = context.getString(R.string.stats_header_menu_planning_description)
        val expanded = context.getString(R.string.stats_header_menu_planning_expanded)
        val collapsed = context.getString(R.string.stats_header_menu_planning_collapsed)
        val hits = PlanningActionHits()

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                StatsScreen(
                    state = StatsUiState(),
                    actions = statsPlanningMenuActions(hits),
                )
            }
        }

        val menu = composeRule.onNodeWithContentDescription(menuDescription)
        menu.assert(hasStateDescription(collapsed))
        val bounds = menu.getUnclippedBoundsInRoot()
        assertDpAtLeast(expected = 48.dp, actual = bounds.bottom - bounds.top)

        menu.performClick()
        composeRule.waitForIdle()

        composeRule.onNodeWithContentDescription(menuDescription)
            .assert(hasStateDescription(expanded))
        assertPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.Budget,
            label = context.getString(R.string.stats_header_open_budget),
        )
        assertPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.IncomePlans,
            label = context.getString(R.string.stats_header_open_income_plans),
        )
        assertPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.DebtGoals,
            label = context.getString(R.string.stats_header_open_debt_goals),
        )

        clickPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.SpendingGoal,
            assertHit = { assertEquals(1, hits.spendingGoal) },
        )
        openPlanningMenu(menuDescription)
        clickPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.Budget,
            assertHit = { assertEquals(1, hits.budget) },
        )
        openPlanningMenu(menuDescription)
        clickPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.Recurring,
            assertHit = { assertEquals(1, hits.recurring) },
        )
        openPlanningMenu(menuDescription)
        clickPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.IncomePlans,
            assertHit = { assertEquals(1, hits.incomePlans) },
        )
        openPlanningMenu(menuDescription)
        clickPlanningMenuItem(
            tag = StatsPlanningMenuTestTags.DebtGoals,
            assertHit = { assertEquals(1, hits.debtGoals) },
        )
    }

    private fun openPlanningMenu(menuDescription: String) {
        composeRule.onNodeWithContentDescription(menuDescription).performClick()
        composeRule.waitForIdle()
    }

    private fun clickPlanningMenuItem(
        tag: String,
        assertHit: () -> Unit,
    ) {
        composeRule.onNodeWithTag(tag).performClick()
        composeRule.waitForIdle()
        assertHit()
    }

    private fun assertPlanningMenuItem(
        tag: String,
        label: String,
    ) {
        composeRule.onNodeWithTag(tag)
            .assert(hasText(label))
            .assertIsDisplayed()
    }

    private fun hasStateDescription(value: String): SemanticsMatcher {
        return SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, value)
    }

    private fun assertDpAtLeast(expected: Dp, actual: Dp) {
        assertTrue(
            "Expected planning menu touch target height >= $expected, got $actual",
            actual.value + DP_EPSILON >= expected.value,
        )
    }

    private fun statsPlanningMenuActions(hits: PlanningActionHits) = StatsScreenActions(
        filters = StatsFilterActions(
            onMonthChange = {},
            onTagChange = {},
        ),
        onRefresh = {},
        planning = StatsPlanningActions(
            onOpenSpendingGoal = { hits.spendingGoal++ },
            onOpenBudget = { hits.budget++ },
            onOpenRecurring = { hits.recurring++ },
            onOpenIncomePlans = { hits.incomePlans++ },
            onOpenDebtGoals = { hits.debtGoals++ },
        ),
        reports = StatsReportActions(
            onDrillToLedger = {},
            onGranularityChange = {},
            onRankingMetricChange = {},
        ),
    )

    private data class PlanningActionHits(
        var spendingGoal: Int = 0,
        var budget: Int = 0,
        var recurring: Int = 0,
        var incomePlans: Int = 0,
        var debtGoals: Int = 0,
    )

    private companion object {
        const val DP_EPSILON = 0.01f
    }
}
