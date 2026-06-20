package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.junit4.v2.createComposeRule
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.screens.expense.TAG_TAGS_FIELD
import com.ticketbox.ui.screens.expense.TAG_VALUE_SCORE_FIELD
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ExpenseEditUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test

class ExpenseEditScreenContractTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun expenseTimeAndMoreSectionClicksStayStableAndSubmitDraft() {
        var retryCount = 0
        var savedDraft: ExpenseDraft? = null

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpenseEditScreen(
                    expense = expense(),
                    state = ExpenseEditUiState(
                        categories = listOf("餐饮", "交通", "其他"),
                    ),
                    onSave = { savedDraft = it },
                    onConfirm = {},
                    onReject = {},
                    onRetryOcr = { retryCount += 1 },
                    onLoadFullImage = {},
                    onKeepDuplicate = {},
                    onDone = {},
                )
            }
        }

        composeRule.onNodeWithText("选日期").performScrollTo().performClick()
        composeRule.onNodeWithText("选择日期").assertIsDisplayed()
        composeRule.onNodeWithText("取消").performClick()

        composeRule.onNodeWithText("选时间").performScrollTo().performClick()
        composeRule.onNodeWithText("选择时间").assertIsDisplayed()
        composeRule.onNodeWithText("取消").performClick()

        composeRule.onNodeWithText("展开").performScrollTo().performClick()
        // Locate the 「更多记录」inputs by stable testTag, not the Material3 label/value text node
        // (which isn't reliably exposed in the semantics tree — was the flaky "标签" lookup).
        composeRule.onNodeWithTag(TAG_TAGS_FIELD).performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithTag(TAG_TAGS_FIELD).performTextReplacement("家庭")
        composeRule.onNodeWithTag(TAG_VALUE_SCORE_FIELD).performScrollTo()
        composeRule.onNodeWithText("查看识别原文").performScrollTo().performClick()
        composeRule.onNodeWithText("重新识别").performScrollTo().performClick()
        // 「保存」现在浮在底部操作栏（不在滚动流里），无需 performScrollTo——
        // 永远一拇指可达正是批 9 的目标。
        composeRule.onNodeWithText("保存").performClick()

        composeRule.runOnIdle {
            assertEquals(1, retryCount)
            assertNotNull(savedDraft)
            val draft = savedDraft!!
            assertEquals("家庭", draft.tags)
            assertEquals(3, draft.valueScore)
            assertEquals(1, draft.regretScore)
            assertEquals("2026-05-12T10:15:00Z", draft.expenseTime)
        }
    }

    @Test
    fun pendingActionBarShowsConfirmRejectWithoutScrolling() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpenseEditScreen(
                    expense = expense(),
                    state = ExpenseEditUiState(),
                    onSave = {},
                    onConfirm = {},
                    onReject = {},
                    onRetryOcr = {},
                    onLoadFullImage = {},
                    onKeepDuplicate = {},
                    onDone = {},
                    allowConfirm = true,
                    allowReject = true,
                )
            }
        }

        // pending 态：确认入账 / 保存 / 忽略 都在浮动栏里，开屏即可见。
        composeRule.onNodeWithText("确认入账").assertIsDisplayed()
        composeRule.onNodeWithText("保存").assertIsDisplayed()
        composeRule.onNodeWithText("忽略").assertIsDisplayed()
    }

    @Test
    fun confirmedExpenseActionBarHidesConfirmAndReject() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpenseEditScreen(
                    expense = expense().copy(status = "confirmed"),
                    state = ExpenseEditUiState(),
                    onSave = {},
                    onConfirm = {},
                    onReject = {},
                    onRetryOcr = {},
                    onLoadFullImage = {},
                    onKeepDuplicate = {},
                    onDone = {},
                    allowConfirm = false,
                    allowReject = false,
                )
            }
        }

        // 已入账：只剩保存 + 返回，确认/忽略收起（语义对齐 ExpenseEditRoute）。
        composeRule.onNodeWithText("保存").assertIsDisplayed()
        composeRule.onNodeWithText("返回").assertIsDisplayed()
        composeRule.onNodeWithText("确认入账").assertDoesNotExist()
        composeRule.onNodeWithText("忽略").assertDoesNotExist()
    }

    @Test
    fun billSplitSourceRendersHumanLabelNotRawToken() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ExpenseEditScreen(
                    expense = expense().copy(source = "bill_split_received"),
                    state = ExpenseEditUiState(readOnly = true),
                    onSave = {},
                    onConfirm = {},
                    onReject = {},
                    onRetryOcr = {},
                    onLoadFullImage = {},
                    onKeepDuplicate = {},
                    onDone = {},
                )
            }
        }

        // 来源行不再漏裸 token：bill_split_received → 来源：拆账。
        composeRule.onNodeWithText("来源：拆账").performScrollTo().assertIsDisplayed()
    }

    private fun expense(): Expense = Expense(
        id = 1L,
        publicId = "pub-1",
        amountCents = 1234L,
        merchant = "QA Merchant",
        category = "其他",
        note = "qa pending edit flow",
        source = "android-qa",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = "qa raw text line 1\nqa raw text line 2",
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = "qa",
        valueScore = 3,
        regretScore = 1,
        status = "pending",
        expenseTime = "2026-05-12T10:15:00Z",
        createdAt = "2026-05-13T13:10:55Z",
        updatedAt = "2026-05-13T13:10:55Z",
        rowVersion = 1L,
        confirmedAt = null,
        rejectedAt = null,
    )
}
