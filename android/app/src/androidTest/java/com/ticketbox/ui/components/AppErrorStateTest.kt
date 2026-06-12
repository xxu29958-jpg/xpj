package com.ticketbox.ui.components

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * 审计 8.4: AppErrorState is the unified failure surface (说明 + 「重试」) — distinct
 * from the loading / empty states it visually mirrors. These pin (a) title, body and
 * the 重试 button render, and (b) tapping 重试 fires onRetry. It draws the danger
 * StateTone so it stays readable across paper / mono / midnight; the per-skin color
 * triple itself is pinned in AppStatusBannerTest.
 *
 * Lives in androidTest (Compose render assertions need the device runtime); does not
 * touch the src/test @Test baseline.
 */
class AppErrorStateTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun rendersTitleBodyAndRetry() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppErrorState(
                    title = "统计没能打开",
                    body = "可能是网络不稳定或电脑端没在运行。",
                    onRetry = {},
                )
            }
        }

        composeRule.onNodeWithText("统计没能打开").assertIsDisplayed()
        composeRule.onNodeWithText("可能是网络不稳定或电脑端没在运行。").assertIsDisplayed()
        composeRule.onNodeWithText("重试").assertIsDisplayed()
    }

    @Test
    fun retryButtonFiresCallback() {
        var retried = 0
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppErrorState(
                    title = "预算没能打开",
                    body = "稍后再来。",
                    onRetry = { retried += 1 },
                )
            }
        }

        composeRule.onNodeWithText("重试").performClick()

        assertEquals(1, retried)
    }
}
