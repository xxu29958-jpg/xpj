package com.ticketbox.ui.components

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.navigation.PrimaryDomain
import com.ticketbox.ui.navigation.toPrimaryNavItem
import com.ticketbox.ui.saveConsumerArtPreview
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
        var selectedKey by mutableStateOf(PrimaryDomain.Inbox.key)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppBottomNav(
                    items = PrimaryDomain.entries.map { it.toPrimaryNavItem() },
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

        saveConsumerArtPreview("primary-navigation-paper", composeRule.onRoot().captureToImage().asAndroidBitmap())
        composeRule.onNodeWithContentDescription("流水").performClick()
        composeRule.waitForIdle()

        assertEquals(PrimaryDomain.Transactions.key, selectedKey)
    }

    private fun assertDpWithin(expected: Dp, actual: Dp) {
        val delta = abs(expected.value - actual.value)
        assertTrue("Expected $actual to be within 0.5.dp of $expected", delta <= 0.5f)
    }

    private companion object {
        val bottomNavLabels = listOf("收件", "流水", "往来", "计划", "洞察")
    }
}
