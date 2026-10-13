package com.ticketbox.ui.screens.pending

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.PendingUploadOriginalUi
import com.ticketbox.viewmodel.PendingUploadUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

class PendingCaptureReadabilityTest {
    @get:Rule val compose = createComposeRule()

    @Test fun readOnlyRecoveryKeepsLongOriginalsReadableAndTheirReceiptReachable() {
        val name = "家庭共同采买的一张很长名称的小票原图，需要保留并核实原来的上传结果.png"
        var opened: Long? = null
        var retries = 0
        val state = PendingUiState(readOnly = true, upload = PendingUploadUiState(
            groupId = "original-group", retryable = true,
            originals = listOf(PendingUploadOriginalUi(1, name, PendingMutationStatus.Unknown),
                PendingUploadOriginalUi(2, "已经收到的小票.png", PendingMutationStatus.Done, 42)),
        ))
        val actions = PendingScreenChromeActions({}, {}, {}, {}, {}, { retries++ }, {},
            PendingUploadSelectionUiState(0, false, {}, {}), onOpenUploadExpense = { opened = it })
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                PendingCaptureSheet(state, actions, onOpenExpense = {}, onDismiss = {})
            }
        }
        compose.onNodeWithText("小票正在整理").assertIsDisplayed()
        capture("capture-readonly-header")
        compose.onNodeWithText("重试上传").assertDoesNotExist()
        val layouts = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText(name).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
        assertFalse(layouts.single().hasVisualOverflow)
        compose.onNodeWithText("查看原单").performScrollTo().assertIsDisplayed()
        capture("capture-readonly-original")
        compose.onNodeWithText("查看原单").performClick()
        assertEquals(42L, opened)
        assertEquals(0, retries)
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(100, 2_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }
}
