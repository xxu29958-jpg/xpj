package com.ticketbox.ui.navigation

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class MainQuickActionsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun viewerMenuKeepsReviewAndRemovesWriteActions() {
        var selected: ShortcutTarget? = null
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                MainQuickActionsButton(
                    canModify = false,
                    onAction = { selected = it },
                )
            }
        }

        composeRule.onNodeWithContentDescription("快捷操作").performClick()
        composeRule.onNodeWithText("传小票").assertDoesNotExist()
        composeRule.onNodeWithText("记一笔").assertDoesNotExist()
        composeRule.onNodeWithText("去确认").assertIsDisplayed().performClick()

        composeRule.runOnIdle {
            assertEquals(ShortcutTarget.ReviewPending, selected)
        }
    }
}
