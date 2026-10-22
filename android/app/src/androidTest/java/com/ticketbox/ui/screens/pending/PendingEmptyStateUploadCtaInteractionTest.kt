package com.ticketbox.ui.screens.pending

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingEnrichmentFeedback
import com.ticketbox.viewmodel.PendingEnrichmentFeedbackKind
import com.ticketbox.viewmodel.PendingEnrichmentUiState
import com.ticketbox.viewmodel.PendingListLoadState
import com.ticketbox.viewmodel.PendingUiState
import com.ticketbox.viewmodel.PendingUploadOriginalUi
import com.ticketbox.viewmodel.PendingUploadUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Exercises the production page across loading/empty transitions and task acknowledgement. */
class PendingEmptyStateUploadCtaInteractionTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun loadingAndEmptyKeepTheSameSingleUploadEntryAndImagePickerCallback() {
        var uploads = 0
        val state = mutableStateOf(PendingUiState(loading = true, listLoadState = PendingListLoadState.Loading))
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) { inbox(state.value, chrome(upload = { uploads++ })) }
        }
        val hero = compose.onNodeWithText("收好生活里的小票").assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        capture("inbox-stable-loading")
        compose.runOnIdle { state.value = state.value.copy(loading = false, hasLoadedOnce = true, listLoadState = PendingListLoadState.Loaded) }
        compose.onNodeWithText("还没有待处理的小票").assertIsDisplayed()
        assertEquals(hero, compose.onNodeWithText("收好生活里的小票").assertIsDisplayed().fetchSemanticsNode().boundsInRoot)
        compose.onAllNodes(hasText("上传小票")).assertCountEquals(1)
        capture("inbox-stable-empty")
        compose.onNodeWithText("上传小票").performClick()
        compose.runOnIdle { assertEquals(1, uploads) }
    }

    @Test
    fun midnightReadOnlyEmptyStateExplainsWithoutOfferingUpload() {
        var refreshes = 0
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                inbox(PendingUiState(readOnly = true, listLoadState = PendingListLoadState.Loaded), chrome(refresh = { refreshes++ }))
            }
        }
        compose.onNodeWithText("还没有待处理的小票").assertIsDisplayed()
        compose.onNodeWithText("上传小票").assertDoesNotExist()
        compose.onNodeWithText("刷新").performClick()
        compose.runOnIdle { assertEquals(1, refreshes) }
        capture("inbox-stable-midnight-viewer")
    }

    @Test
    fun closingCompletedTaskHidesItsSummaryAndToolsStillOpenTheOriginalReceipt() {
        var openedExpense: Long? = null
        val state = mutableStateOf(PendingUiState(listLoadState = PendingListLoadState.Loaded,
            upload = PendingUploadUiState(showSummary = true,
                originals = listOf(PendingUploadOriginalUi(1, "receipt.png", PendingMutationStatus.Done, 42)))))
        val actions = chrome().copy(onOpenUploadExpense = { openedExpense = it }, onDismissCompletedUpload = {
            state.value = state.value.copy(upload = state.value.upload.copy(showSummary = false))
        })
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) { inbox(state.value, actions) } }
        compose.onNodeWithText("查看上传任务").performScrollTo().performClick()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        compose.onNodeWithText(context.getString(R.string.pending_capture_back)).assertIsDisplayed().performClick()
        compose.onNodeWithText("查看上传任务").assertDoesNotExist()
        compose.onNodeWithContentDescription("收件工具").performClick()
        compose.onNodeWithText("近期上传").performClick()
        compose.onNodeWithText("receipt.png").assertIsDisplayed()
        compose.onNodeWithText("查看原单").assertIsDisplayed()
        saveConsumerArtPreview("inbox-completed-history", compose.onNode(isDialog()).captureToImage().asAndroidBitmap())
        compose.onNodeWithText("查看原单").performClick()
        compose.runOnIdle { assertEquals(42L, openedExpense) }
    }

    @Test
    fun failedRecognitionOffersOpenAndDismissAndDisappearsWithItsExpense() {
        val targetPresent = mutableStateOf(true)
        val state = mutableStateOf(PendingEnrichmentUiState(feedback = PendingEnrichmentFeedback(42, PendingEnrichmentFeedbackKind.Failed)))
        var opened = 0
        var retries = 0
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PendingEnrichmentStatusBand(state.value, targetPresent.value, { opened++ }, { retries++ },
                    onDismissFeedback = { state.value = state.value.copy(feedback = null) })
            }
        }
        compose.onNodeWithText("打开账单").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, opened) }
        capture("inbox-recognition-actions")
        compose.onNodeWithText("关闭提示").assertIsDisplayed().performClick()
        compose.onNodeWithText("打开账单").assertDoesNotExist()
        compose.runOnIdle {
            state.value = PendingEnrichmentUiState(feedback = PendingEnrichmentFeedback(42, PendingEnrichmentFeedbackKind.Failed))
            targetPresent.value = false
        }
        compose.onNodeWithText("自动识别失败", substring = true).assertDoesNotExist()
        compose.runOnIdle {
            state.value = PendingEnrichmentUiState(feedback = PendingEnrichmentFeedback(42, PendingEnrichmentFeedbackKind.Unavailable))
        }
        compose.onNodeWithText("关闭提示").assertDoesNotExist()
        compose.onNodeWithText("重试检查").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, retries) }
    }

    private fun capture(name: String) = saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
}

private fun chrome(upload: () -> Unit = {}, refresh: () -> Unit = {}) =
    PendingScreenChromeActions(refresh, upload, {}, {}, {}, {}, {}, PendingUploadSelectionUiState(0, false, {}, {}))

@androidx.compose.runtime.Composable
private fun inbox(state: PendingUiState, chrome: PendingScreenChromeActions) {
    PendingScreen(state, chrome, PendingExpenseQueueActions({}, {}, {}, {}),
        PendingReviewFlowActions(PendingQuickFixEntryActions({}, {}, {}), PendingDuplicateReviewActions({}), PendingQueueReviewActions({}, {})),
        PendingReviewSheetHostActions({ _, _ -> }, { _, _ -> }, { _, _ -> }, { _, _ -> }, {}, {}, {}, {}, {}, onReviewInputChange = {}))
}
