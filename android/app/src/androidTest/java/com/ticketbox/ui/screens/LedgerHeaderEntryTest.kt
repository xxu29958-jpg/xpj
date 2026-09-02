package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerUiState
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * W2-B 流水页头部/空态纪律（pending 单入口模式的 ledger 对应物）：
 * - 「记一笔」全屏最多一个入口：有内容/加载/失败→头部；空屏落定→空态；Viewer→无；
 * - 空态单一 CTA（有筛选=重置筛选；无筛选=记一笔），不再有常驻「更新账本」按钮
 *   （刷新由下拉刷新 + 头部新鲜度行 + 工具内的同步承担，能力不退化）；
 * - 搜索从工具 sheet 提为头部一级入口；
 * - 「工具」文字链接退役为图标入口；
 * - Viewer 的只读权限行与新鲜度缓存条同时可见（正交，互不掩盖）。
 */
class LedgerHeaderEntryTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun writerContentKeepsSingleRecordCta() {
        render(LedgerUiState(items = listOf(confirmedRow()), syncedInCurrentSession = true))

        assertRecordCtaCount(1)
    }

    @Test
    fun writerEmptyUnfilteredHasSingleRecordCtaAndNoRefreshButton() {
        render(LedgerUiState(monthFilter = "", syncedInCurrentSession = true))

        assertRecordCtaCount(1)
        composeRule.onAllNodesWithText("更新账本").assertCountEquals(0)
    }

    @Test
    fun writerEmptyFilteredKeepsClearFiltersAsOnlyEmptyCta() {
        render(LedgerUiState(syncedInCurrentSession = true))

        assertRecordCtaCount(1)
        composeRule.onAllNodesWithText("重置筛选").assertCountEquals(1)
        composeRule.onAllNodesWithText("更新账本").assertCountEquals(0)
    }

    @Test
    fun viewerEmptyHasNoRecordCtaAndFreshnessIsNotMaskedByPermission() {
        render(LedgerUiState(readOnly = true))

        assertRecordCtaCount(0)
        // 权限条/新鲜度条都把标题与正文合成一个 AnnotatedString 节点，断言子串即可。
        composeRule.onNodeWithText("只读模式", substring = true).assertExists()
        composeRule.onNodeWithText("可能不是最新。", substring = true).assertExists()
    }

    @Test
    fun headerExposesSearchAsFirstClassEntry() {
        var searchOpened = false
        render(
            LedgerUiState(items = listOf(confirmedRow()), syncedInCurrentSession = true),
            actions = LedgerScreenActions(onOpenGlobalSearch = { searchOpened = true }),
        )

        composeRule.onNodeWithContentDescription("搜索").performClick()
        assertTrue(searchOpened)
    }

    @Test
    fun toolsEntryIsIconButtonNotTextLink() {
        render(LedgerUiState(items = listOf(confirmedRow()), syncedInCurrentSession = true))

        composeRule.onAllNodesWithText("工具").assertCountEquals(0)
        composeRule.onNodeWithContentDescription("账本工具").assertExists()
    }

    private fun assertRecordCtaCount(expected: Int) {
        val total = composeRule.onAllNodesWithText("记一笔").fetchSemanticsNodes().size +
            composeRule.onAllNodesWithText("手动记一笔").fetchSemanticsNodes().size
        org.junit.Assert.assertEquals(expected, total)
    }

    private fun render(state: LedgerUiState, actions: LedgerScreenActions = LedgerScreenActions()) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LedgerScreen(state = state, actions = actions)
            }
        }
    }
}

private fun confirmedRow(): ConfirmedStreamItem = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-09-01",
    streamAmountCents = 1280L,
    root = Expense(
        id = 1L,
        publicId = "ledger-entry-1",
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
        status = "confirmed",
        expenseTime = "2026-09-01T08:00:00Z",
        createdAt = "2026-09-01T08:00:00Z",
        updatedAt = "2026-09-01T08:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-09-01T08:05:00Z",
        rejectedAt = null,
    ),
    lineageStatus = ExpenseLineageStatus.Confirmed,
    lineageHomeNetCents = 1280L,
)
