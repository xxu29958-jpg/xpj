package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.adaptive.currentWindowAdaptiveInfo
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.WindowSize
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasAnyDescendant
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isSelected
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptiveLayoutPolicy
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingListLoadState
import com.ticketbox.viewmodel.PendingSheet
import com.ticketbox.viewmodel.PendingUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * expanded 宽度下复核提升为常驻 supporting pane 的版面回归（W2-A 真机崩溃：
 * 点击「补金额」即 IllegalStateException——外层 AppAdaptiveSupportingPane 的
 * verticalScroll 给子级无限高约束，与 AppSheetScaffold 自身 verticalScroll
 * 嵌套）。pane 槽位本身有界：复核内容必须在有限高度内完成测量，由 sheet
 * 内部滚动承担溢出。本测试直接消费生产 seam [PendingSupportingPaneBody]，
 * 守护「Review 不再套外层滚动容器」这一接线合同。
 */
class PendingExpandedReviewPaneLayoutTest {
    @get:Rule
    val composeRule = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()

    @Test
    fun expandedReviewPaneKeepsTheOriginalJpyDraftActionAboveTheKeyboard() {
        val drafts = mutableListOf<Pair<Long, Long>>()
        val input = androidx.compose.runtime.mutableStateOf(com.ticketbox.viewmodel.PendingReviewValues())
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                Box(modifier = Modifier.width(420.dp).height(760.dp)) {
                    PendingSupportingPaneBody(
                        content = PendingSupportingPaneContent.Review(
                            PendingSheet.MissingAmount(missingAmountExpense()),
                        ),
                        reviewState = reviewState(PendingSheet.MissingAmount(missingAmountExpense())).copy(inputValues = input.value),
                        reviewActions = reviewActions { id, amount -> drafts += id to amount }.copy(onReviewInputChange = { input.value = it }),
                        triageContent = {},
                    )
                }
            }
        }

        composeRule.onNodeWithText("补全金额").assertExists()
        composeRule.onNode(hasSetTextAction()).performTouchInput { click() }.performTextInput("1234")
        val save = InstrumentationRegistry.getInstrumentation().targetContext
            .getString(R.string.pending_missing_amount_save_draft)
        keyboard.assertActionAboveKeyboard(composeRule, save, "pending-pane-jpy-keyboard")
        composeRule.onNodeWithText(save).performTouchInput { click() }
        composeRule.runOnIdle { assertEquals(listOf(1L to 1234L), drafts) }
    }

    /** DW2：宽窗队列在主栏，复核常驻辅助区；队列标出正在核对的一行，不再另给「开始核对」。 */
    @Test
    fun wideInboxKeepsTheQueueBesideTheSingleReviewPane() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val queue = listOf(
            missingAmountExpense().copy(id = 11L, publicId = "wide-11", merchant = "便利店", category = "", amountCents = 128_60,
                originalCurrencyCode = CurrencyCode.CNY),
            missingAmountExpense().copy(id = 12L, publicId = "wide-12", merchant = "出租车", category = "交通", amountCents = 32_00,
                originalCurrencyCode = CurrencyCode.CNY),
            missingAmountExpense().copy(id = 13L, publicId = "wide-13", merchant = "街角小馆", category = "餐饮",
                originalCurrencyCode = CurrencyCode.CNY),
        )
        val state = mutableStateOf(PendingUiState(items = queue, listLoadState = PendingListLoadState.Loaded, hasLoadedOnce = true,
            categoryOptions = listOf("购物", "餐饮", "交通")))
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.WindowSize(DpSize(1000.dp, 640.dp))) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    CompositionLocalProvider(
                        LocalAppAdaptiveLayoutPolicy provides
                            currentWindowAdaptiveInfo(supportLargeAndXLargeWidth = true).toAppAdaptiveLayoutPolicy(),
                    ) {
                        PendingScreen(state.value, chromeActions(), PendingExpenseQueueActions({}, {}, {}, {}),
                            PendingReviewFlowActions(PendingQuickFixEntryActions({}, {}, {}), PendingDuplicateReviewActions({}),
                                PendingQueueReviewActions({}, {})),
                            reviewActions { _, _ -> })
                    }
                }
            }
        }
        val startReview = context.getString(R.string.pending_start_review)
        val reviewing = context.getString(R.string.pending_row_signal_reviewing)
        composeRule.onNodeWithText(startReview).assertIsDisplayed()
        composeRule.onNodeWithText(reviewing).assertDoesNotExist()
        saveConsumerArtPreview("inbox-wide-queue", composeRule.onRoot().captureToImage().asAndroidBitmap())

        composeRule.runOnIdle { state.value = state.value.copy(activeSheet = PendingSheet.QuickCategory(queue[0])) }
        val supporting = paneBounds(AppAdaptivePaneStructures.Inbox.supportingTestTag)
        val primary = paneBounds(AppAdaptivePaneStructures.Inbox.primaryTestTag)
        val title = composeRule.onNodeWithText(context.getString(R.string.quick_category_sheet_title))
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("Review must live in the supporting pane: $title vs $supporting", title.left >= supporting.left)
        val marker = composeRule.onNodeWithText(reviewing).assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("The reviewed row is marked in the queue: $marker vs $primary", marker.right <= primary.right)
        composeRule.onAllNodes(isSelected() and hasAnyDescendant(hasText("便利店"))).assertCountEquals(1)
        composeRule.onNodeWithText(startReview).assertDoesNotExist()
        saveConsumerArtPreview("inbox-wide-review", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }

    private fun paneBounds(tag: String): Rect =
        composeRule.onNodeWithTag(tag).assertIsDisplayed().fetchSemanticsNode().boundsInRoot

    private fun chromeActions() = PendingScreenChromeActions({}, {}, {}, {}, {}, {}, {},
        PendingUploadSelectionUiState(pendingCount = 0, accepting = false, onRetry = {}, onStop = {}))
}

private fun reviewState(sheet: PendingSheet) = PendingReviewSheetHostState(
    sheet = sheet,
    categoryOptions = emptyList(),
    actionInProgressIds = emptySet(),
    readyCount = 0,
    missingAmountSkip = 1,
    duplicateSkip = 0,
    bulkRunning = false,
    bulkConfirmed = 0,
    bulkTotal = 0,
    reviewRemaining = 1,
    statusMessage = null,
)

private fun reviewActions(saveDraft: (Long, Long) -> Unit) = PendingReviewSheetHostActions(
    onSaveQuickCategory = { _, _ -> },
    onSaveQuickMerchant = { _, _ -> },
    onSaveAmountDraft = { expense, amount -> saveDraft(expense.id, amount) },
    onSaveAmountAndConfirm = { _, _ -> error("Saving a draft must not confirm the expense") },
    onSkipReviewField = {},
    onKeepBoth = {},
    onIgnoreCurrent = {},
    onConfirmReady = {},
    onDismiss = {},
    onReviewInputChange = {},
)

private fun missingAmountExpense(): Expense = Expense(
    id = 1L,
    publicId = "pending-pane-1",
    amountCents = null,
    originalCurrencyCode = CurrencyCode.JPY,
    merchant = "咖啡店",
    category = "餐饮",
    note = null,
    source = ExpenseSourceValues.ANDROID_SCREENSHOT,
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "pending",
    expenseTime = "2026-07-08T08:00:00Z",
    createdAt = "2026-07-08T08:00:00Z",
    updatedAt = "2026-07-08T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = null,
    rejectedAt = null,
)
