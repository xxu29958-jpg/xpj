package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingSheet
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

    @Test
    fun expandedReviewPaneMeasuresInsideBoundedSlot() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                Box(modifier = Modifier.width(420.dp).height(760.dp)) {
                    PendingSupportingPaneBody(
                        content = PendingSupportingPaneContent.Review(
                            PendingSheet.MissingAmount(missingAmountExpense()),
                        ),
                        reviewState = reviewState(PendingSheet.MissingAmount(missingAmountExpense())),
                        reviewActions = noopActions(),
                        triageContent = {},
                    )
                }
            }
        }

        composeRule.onNodeWithText("补全金额").assertExists()
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

private fun noopActions() = PendingReviewSheetHostActions(
    onSaveQuickCategory = { _, _ -> },
    onSaveQuickMerchant = { _, _ -> },
    onSaveAmountDraft = { _, _ -> },
    onSaveAmountAndConfirm = { _, _ -> },
    onSkipReviewField = {},
    onKeepBoth = {},
    onIgnoreCurrent = {},
    onConfirmReady = {},
    onDismiss = {},
)

private fun missingAmountExpense(): Expense = Expense(
    id = 1L,
    publicId = "pending-pane-1",
    amountCents = null,
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
