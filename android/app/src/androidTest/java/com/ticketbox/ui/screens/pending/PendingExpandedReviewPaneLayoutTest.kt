package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.ForcedSize
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performScrollTo
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
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAdaptivePaneMode
import com.ticketbox.ui.design.AppAdaptivePostureConstraint
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
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

    @Test
    fun dw2ExpandedInboxKeepsTheQueueBesideItsExistingReviewOwner() {
        val expense = missingAmountExpense()
        val policy = AppAdaptiveLayoutPolicy(
            widthClass = AppWindowWidthClass.Expanded,
            paneMode = AppAdaptivePaneMode.ExpandedSupporting,
            primaryNavigation = AppPrimaryNavigationMode.Rail,
            postureConstraint = AppAdaptivePostureConstraint.None,
        )
        composeRule.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(1440.dp, 900.dp))) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    CompositionLocalProvider(LocalAppAdaptiveLayoutPolicy provides policy) {
                        PendingScreen(
                            state = PendingUiState(
                                items = listOf(expense), listLoadState = PendingListLoadState.Loaded,
                                hasLoadedOnce = true, activeSheet = PendingSheet.MissingAmount(expense),
                                reviewRemaining = 1,
                            ),
                            chromeActions = PendingScreenChromeActions(
                                onRefresh = {}, onUploadScreenshot = {},
                                onOpenRepaymentReview = {}, onOpenDataQuality = {},
                                onRetryEnrichment = {}, onRetryCapacityUpload = {},
                                onDiscardCapacityUpload = {},
                                uploadSelection = PendingUploadSelectionUiState(0, false, {}, {}),
                            ),
                            itemActions = PendingExpenseQueueActions({}, {}, {}, {}),
                            reviewActions = PendingReviewFlowActions(
                                quickFix = PendingQuickFixEntryActions({}, {}, {}),
                                duplicate = PendingDuplicateReviewActions({}),
                                queue = PendingQueueReviewActions({}, {}),
                            ),
                            sheetActions = reviewActions { _, _ -> },
                        )
                    }
                }
            }
        }
        val queue = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Inbox.primaryTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        val review = composeRule.onNodeWithTag(AppAdaptivePaneStructures.Inbox.supportingTestTag)
            .assertIsDisplayed().fetchSemanticsNode().boundsInRoot
        assertTrue("DW2 queue and original review must stay side by side", queue.right <= review.left)
        // MissingAmountSheetContent autofocuses its input. A real user may have to scroll the
        // sheet back to its header when the IME moves the viewport; preserve a visible-title
        // assertion instead of treating an offscreen header as a missing review owner.
        composeRule.onNodeWithText("补全金额").performScrollTo().assertIsDisplayed()
        composeRule.onNode(hasSetTextAction()).assertExists()
        saveConsumerArtPreview("dw2-inbox-wide-active-review-paper", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }
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
