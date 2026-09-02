package com.ticketbox.ui.screens.pending

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * 待确认行写入口的诚实投影（W2-A populated-viewer 反例）：
 * - Viewer 没有写命令——不渲染 mutation CTA（禁用态暗示「别的时候能」，是撒谎）；
 * - Owner/Member 正常显示；busy 只禁用，不隐藏；
 * - 行本体（商户/金额/信号）对 Viewer 保留，读能力不退化。
 */
class PendingViewerRowCtaTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun viewerRowRendersNoMutationCta() {
        row(readOnly = true, busy = false, canMutate = false)

        composeRule.onNodeWithText("确认入账").assertDoesNotExist()
        composeRule.onNodeWithText("咖啡店").assertIsDisplayed()
    }

    @Test
    fun busyWriterRowKeepsCtaDisabled() {
        row(readOnly = false, busy = true, canMutate = false)

        composeRule.onNodeWithText("确认入账").assertIsNotEnabled()
    }

    @Test
    fun writerRowCtaEnabled() {
        row(readOnly = false, busy = false, canMutate = true)

        composeRule.onNodeWithText("确认入账").assertIsEnabled()
    }

    private fun row(readOnly: Boolean, busy: Boolean, canMutate: Boolean) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PendingExpenseReviewRow(
                    item = PendingExpenseReviewItem(
                        expense = confirmReadyExpense(),
                        thumbnail = null,
                        compact = false,
                        showInlineActions = false,
                        busy = busy,
                        readOnly = readOnly,
                    ),
                    actions = PendingExpenseReviewActions(
                        canMutate = canMutate,
                        onEdit = {},
                        onPrimaryAction = {},
                        onReject = {},
                        onKeepDuplicate = {},
                    ),
                )
            }
        }
    }
}

private fun confirmReadyExpense(): Expense = Expense(
    id = 1L,
    publicId = "pending-viewer-1",
    amountCents = 1280L,
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
