package com.ticketbox.ui.screens

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.StatsUiState
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class StatsPlanningMenuTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun planningMenuAnnouncesExpandedStateAndKeepsTouchTarget() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                StatsScreen(
                    state = StatsUiState(),
                    onMonthChange = {},
                    onTagChange = {},
                    onRefresh = {},
                    onOpenBudget = {},
                    onOpenRecurring = {},
                    onOpenIncomePlans = {},
                    onOpenDebtGoals = {},
                )
            }
        }

        val menu = composeRule.onNodeWithContentDescription(PLANNING_MENU_DESCRIPTION)
        menu.assert(hasStateDescription("已折叠"))
        val bounds = menu.getUnclippedBoundsInRoot()
        assertDpAtLeast(expected = 48.dp, actual = bounds.bottom - bounds.top)

        menu.performClick()
        composeRule.waitForIdle()

        composeRule.onNodeWithContentDescription(PLANNING_MENU_DESCRIPTION)
            .assert(hasStateDescription("已展开"))
        composeRule.onNodeWithText("固定支出").assertIsDisplayed()
        composeRule.onNodeWithText("收入记录").assertIsDisplayed()
        composeRule.onNodeWithText("还债目标").assertIsDisplayed()
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

    private companion object {
        const val DP_EPSILON = 0.01f
        const val PLANNING_MENU_DESCRIPTION = "规划菜单"
    }
}
