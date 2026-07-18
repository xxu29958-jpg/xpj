package com.ticketbox.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.EventNote
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.People
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AppBottomNavLayoutTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun primaryDestinationTargetsStayEqualWidthAndClickable() {
        var selectedKey by mutableStateOf("inbox")
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppBottomNav(
                    items = bottomNavItems(),
                    selectedKey = selectedKey,
                    onSelect = { selectedKey = it.key },
                )
            }
        }
        assertExactlyOneSelected("收件")

        val bounds = bottomNavLabels.map { label ->
            composeRule.onNodeWithText(label).assertIsDisplayed()
            composeRule.onNodeWithContentDescription(label).getUnclippedBoundsInRoot()
        }
        val expectedWidth = bounds.first().right - bounds.first().left
        bounds.forEach { bound ->
            val width = bound.right - bound.left
            val height = bound.bottom - bound.top
            assertDpWithin(expected = expectedWidth, actual = width)
            assertTrue("Expected bottom nav target height >= 48.dp, got $height", height >= 48.dp)
        }

        composeRule.onNodeWithContentDescription("流水").performClick()
        composeRule.waitForIdle()

        assertEquals("transactions", selectedKey)
        assertExactlyOneSelected("流水")
    }

    private fun assertExactlyOneSelected(label: String) {
        composeRule.onAllNodes(isSelected()).assertCountEquals(1)
        composeRule.onNodeWithContentDescription(label).assertIsSelected()
    }

    private fun assertDpWithin(expected: Dp, actual: Dp) {
        val delta = abs(expected.value - actual.value)
        assertTrue("Expected $actual to be within 0.5.dp of $expected", delta <= 0.5f)
    }

    private companion object {
        val bottomNavLabels = listOf("收件", "流水", "往来", "计划", "洞察")

        fun bottomNavItems(): List<AppPrimaryNavItem> = listOf(
            AppPrimaryNavItem("inbox", "收件", Icons.Default.Inbox),
            AppPrimaryNavItem("transactions", "流水", Icons.AutoMirrored.Filled.ReceiptLong),
            AppPrimaryNavItem("obligations", "往来", Icons.Default.People),
            AppPrimaryNavItem("plans", "计划", Icons.AutoMirrored.Filled.EventNote),
            AppPrimaryNavItem("insights", "洞察", Icons.Default.Insights),
        )
    }
}
