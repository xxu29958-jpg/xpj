package com.ticketbox.ui.screens.pending

import android.content.Context
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
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

    @Test
    fun foreignRowWithoutOriginalAmountShowsMissingAmountRatherThanWaitingForFx() {
        row(
            readOnly = false,
            busy = false,
            canMutate = true,
            expense = confirmReadyExpense().copy(
                amountCents = null,
                originalAmountMinor = null,
                originalCurrency = CurrencyCode.USD,
                originalCurrencyCode = CurrencyCode.USD,
                fxStatus = "pending",
            ),
        )
        val context = ApplicationProvider.getApplicationContext<Context>()
        composeRule.onNodeWithText(context.getString(R.string.pending_row_amount_missing)).assertIsDisplayed()
        composeRule.onNodeWithText(context.getString(R.string.pending_row_signal_amount)).assertIsDisplayed()
        composeRule.onNodeWithText(context.getString(R.string.expense_fx_waiting)).assertDoesNotExist()
    }

    private fun row(readOnly: Boolean, busy: Boolean, canMutate: Boolean, expense: Expense = confirmReadyExpense()) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                PendingExpenseReviewRow(
                    item = PendingExpenseReviewItem(
                        expense = expense,
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
