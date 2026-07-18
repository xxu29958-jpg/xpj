package com.ticketbox.ui.screens.plan

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.IncomePlanUiState
import com.ticketbox.viewmodel.RecurringUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class PlanScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun planHubKeepsEveryPlanningCapabilityReachable() {
        val hits = PlanActionHits()
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PlanScreen(
                    data = PlanScreenData(
                        budget = BudgetUiState(),
                        recurring = RecurringUiState(),
                        income = IncomePlanUiState(),
                    ),
                    actions = PlanScreenActions(
                        budgetNavigation = PlanBudgetNavigationActions(
                            onOpenBudget = { hits.budget++ },
                            onOpenAdvice = { hits.budgetAdvice++ },
                        ),
                        onOpenSpendingGoal = { hits.spendingGoal++ },
                        onOpenRecurring = { hits.recurring++ },
                        onOpenIncomePlans = { hits.incomePlans++ },
                        onRefresh = {},
                    ),
                )
            }
        }

        clickDestination(PlanDestinationTestTags.Budget) { assertEquals(1, hits.budget) }
        clickDestination(PlanDestinationTestTags.BudgetAdvice) { assertEquals(1, hits.budgetAdvice) }
        clickDestination(PlanDestinationTestTags.SpendingGoal) { assertEquals(1, hits.spendingGoal) }
        clickDestination(PlanDestinationTestTags.Recurring) { assertEquals(1, hits.recurring) }
        clickDestination(PlanDestinationTestTags.IncomePlans) { assertEquals(1, hits.incomePlans) }

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals(
            0,
            composeRule
                .onAllNodesWithContentDescription(context.getString(R.string.navigation_open_account))
                .fetchSemanticsNodes()
                .size,
        )
    }

    private fun clickDestination(tag: String, assertHit: () -> Unit) {
        composeRule.onNodeWithTag(tag)
            .performScrollTo()
            .assertIsDisplayed()
            .performClick()
        composeRule.waitForIdle()
        assertHit()
    }

    private data class PlanActionHits(
        var budget: Int = 0,
        var budgetAdvice: Int = 0,
        var spendingGoal: Int = 0,
        var recurring: Int = 0,
        var incomePlans: Int = 0,
    )
}
