package com.ticketbox.ui.screens.ledger

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.domain.model.StreamOffset
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * W2-B 反例（before-ledger-owner-data.png）：退款行只剩「退款 +¥98.00」，
 * root 商户被金额槽挤没——金额 Box 只有 widthIn(min)，内部 fillMaxWidth 先吞掉
 * Row 全部宽度。金额槽必须与 LedgerAmountOrPending 同约束（min+max），
 * 商户 weight(1f) 保留可辨宽度；窄宽/大字体下金额完整、商户可辨。
 */
class LedgerOffsetRowLayoutTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun refundRowKeepsMerchantAndAmountBothVisible() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LedgerOffsetRow(
                    state = LedgerOffsetItemState(item = refundRow()),
                    onOpen = {},
                )
            }
        }

        composeRule.onNodeWithText("退款").assertIsDisplayed()
        composeRule.onNodeWithText("盒马鲜生").assertIsDisplayed()
        composeRule.onNodeWithText("+¥98.00", substring = true).assertIsDisplayed()
    }
}

private fun refundRow(): ConfirmedStreamItem.OffsetRow = ConfirmedStreamItem.OffsetRow(
    streamDate = "2026-09-03",
    streamAmountCents = 9800L,
    root = Expense(
        id = 9L,
        publicId = "ledger-offset-root-1",
        amountCents = 18650L,
        merchant = "盒马鲜生",
        category = "购物",
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
        status = "confirmed",
        expenseTime = "2026-09-03T10:40:00Z",
        createdAt = "2026-09-03T10:40:00Z",
        updatedAt = "2026-09-03T10:40:00Z",
        rowVersion = 2L,
        confirmedAt = "2026-09-03T10:41:00Z",
        rejectedAt = null,
    ),
    lineageStatus = ExpenseLineageStatus.PartiallyRefunded,
    lineageHomeNetCents = 8850L,
    offset = StreamOffset(
        publicId = "offset-1",
        kind = StreamOffsetKind.Refund,
        amountCents = 9800L,
        originalAmountMinor = 9800L,
        originalCurrencyCode = "CNY",
        homeCurrencyCode = "CNY",
        category = "购物",
    ),
)
