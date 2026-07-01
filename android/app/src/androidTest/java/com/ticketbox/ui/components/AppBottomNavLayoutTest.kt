package com.ticketbox.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Today
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
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
    fun tabSemanticTargetsStayEqualWidthAndClickable() {
        var selectedKey by mutableStateOf("today")
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppBottomNav(
                    items = bottomNavItems(),
                    selectedKey = selectedKey,
                    onSelect = { selectedKey = it.key },
                )
            }
        }

        val bounds = bottomNavLabels.map { label ->
            composeRule.onNodeWithContentDescription(label).getUnclippedBoundsInRoot()
        }
        val expectedWidth = bounds.first().right - bounds.first().left
        bounds.forEach { bound ->
            val width = bound.right - bound.left
            val height = bound.bottom - bound.top
            assertDpWithin(expected = expectedWidth, actual = width)
            assertTrue("Expected bottom nav target height >= 48.dp, got $height", height >= 48.dp)
        }

        composeRule.onNodeWithContentDescription("账本").performClick()
        composeRule.waitForIdle()

        assertEquals("ledger", selectedKey)
    }

    private fun assertDpWithin(expected: Dp, actual: Dp) {
        val delta = abs(expected.value - actual.value)
        assertTrue("Expected $actual to be within 0.5.dp of $expected", delta <= 0.5f)
    }

    private companion object {
        val bottomNavLabels = listOf("今日", "待确认", "账本", "洞察", "设置")

        fun bottomNavItems(): List<AppBottomNavItem> = listOf(
            AppBottomNavItem("today", "今日", Icons.Default.Today),
            AppBottomNavItem("pending", "待确认", Icons.Default.CheckCircle),
            AppBottomNavItem("ledger", "账本", Icons.AutoMirrored.Filled.ReceiptLong),
            AppBottomNavItem("insights", "洞察", Icons.Default.Insights),
            AppBottomNavItem("settings", "设置", Icons.Default.Settings),
        )
    }
}
