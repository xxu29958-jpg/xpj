package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * W2-C 收入编辑忙碌守门（真机反例 income-busy-hidden.png）：只守 onDismissRequest
 * 挡不住 Back/下滑把 sheet 动画到 Hidden——页面被不可见 modal 遮住、会话悬空。
 * 这里用真实下滑手势走同一条 AnchoredDraggable 路径：忙碌时 Hidden 必须被否决、
 * 内容留在屏上；空闲时下滑正常收起并回调 dismiss。VM 层的 dismiss 守卫是另一层，
 * 不能替代本平台覆盖。
 */
class IncomePlanBusyGuardedSheetTest {

    @get:Rule
    val composeRule = createComposeRule()

    private class Harness {
        var submitting by mutableStateOf(true)
        var dismissed by mutableStateOf(false)
    }

    private fun setSheet(harness: Harness) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                if (!harness.dismissed) {
                    IncomePlanBusyGuardedSheet(
                        isSubmitting = harness.submitting,
                        onDismiss = { harness.dismissed = true },
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(SHEET_CONTENT_HEIGHT)
                                .testTag(SHEET_CONTENT_TAG),
                        )
                    }
                }
            }
        }
        composeRule.waitForIdle()
    }

    @Test
    fun submittingSheetSurvivesSwipeDown() {
        val harness = Harness()
        setSheet(harness)
        composeRule.onNodeWithTag(SHEET_CONTENT_TAG).assertIsDisplayed()

        repeat(SWIPE_ATTEMPTS) {
            composeRule.onNodeWithTag(SHEET_CONTENT_TAG).performTouchInput { swipeDown() }
            composeRule.waitForIdle()
        }

        composeRule.onNodeWithTag(SHEET_CONTENT_TAG).assertIsDisplayed()
        assertTrue(!harness.dismissed)
    }

    @Test
    fun idleSheetSwipeDownDismisses() {
        val harness = Harness()
        setSheet(harness)
        harness.submitting = false
        composeRule.waitForIdle()

        repeat(SWIPE_ATTEMPTS) {
            if (harness.dismissed) return@repeat
            composeRule.onNodeWithTag(SHEET_CONTENT_TAG).performTouchInput { swipeDown() }
            composeRule.waitForIdle()
        }

        assertTrue(harness.dismissed)
    }

    private companion object {
        const val SHEET_CONTENT_TAG = "income_plan_busy_guarded_sheet_content"
        const val SWIPE_ATTEMPTS = 3
        val SHEET_CONTENT_HEIGHT = 400.dp
    }
}
