package com.ticketbox.ui.screens.pending

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.viewmodel.PendingSheet
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * expanded 常驻复核面板的退出权合同（W2-A 把复核从 modal 提升到 pane 后
 * 直接造成的 regression 面）：
 * - 已有内容内取消的 sheet（QuickCategory/QuickMerchant/BulkConfirm）
 *   不再获得 pane 级第二出口，避免双取消；
 * - 缺少内容内取消的 sheet（MissingAmount/Duplicate）由 pane 补一个退出；
 * - 任何 sheet 的在途 mutation 进行中（条目 busy / 批量进行中）一律禁止
 *   退出（含 pane 出口与 Back），不重新打开「在途 mutation 可被隐藏」路径。
 */
class PendingPaneExitTest {
    @Test
    fun sheetsWithInContentCancelGetNoPaneAffordance() {
        listOf(
            PendingSheet.QuickCategory(reviewExpense(1L)),
            PendingSheet.QuickMerchant(reviewExpense(2L)),
            PendingSheet.BulkConfirm,
        ).forEach { sheet ->
            assertEquals(
                PendingPaneExit(showAffordance = false, enabled = true),
                pendingPaneExit(sheet, actionInProgressIds = emptySet(), bulkRunning = false),
            )
        }
    }

    @Test
    fun sheetsWithoutInContentCancelGetAPaneExit() {
        assertEquals(
            PendingPaneExit(showAffordance = true, enabled = true),
            pendingPaneExit(
                PendingSheet.MissingAmount(reviewExpense(3L)),
                actionInProgressIds = emptySet(),
                bulkRunning = false,
            ),
        )
        assertEquals(
            PendingPaneExit(showAffordance = true, enabled = true),
            pendingPaneExit(
                PendingSheet.Duplicate(reviewExpense(4L)),
                actionInProgressIds = emptySet(),
                bulkRunning = false,
            ),
        )
    }

    @Test
    fun exitIsDisabledWhileThatSheetHasAnInFlightMutation() {
        val saving = reviewExpense(5L)
        assertEquals(
            PendingPaneExit(showAffordance = true, enabled = false),
            pendingPaneExit(
                PendingSheet.MissingAmount(saving),
                actionInProgressIds = setOf(5L),
                bulkRunning = false,
            ),
        )
        assertEquals(
            PendingPaneExit(showAffordance = true, enabled = false),
            pendingPaneExit(
                PendingSheet.Duplicate(saving),
                actionInProgressIds = setOf(5L),
                bulkRunning = false,
            ),
        )
        assertEquals(
            PendingPaneExit(showAffordance = false, enabled = false),
            pendingPaneExit(
                PendingSheet.QuickCategory(saving),
                actionInProgressIds = setOf(5L),
                bulkRunning = false,
            ),
        )
        assertEquals(
            PendingPaneExit(showAffordance = false, enabled = false),
            pendingPaneExit(
                PendingSheet.BulkConfirm,
                actionInProgressIds = emptySet(),
                bulkRunning = true,
            ),
        )
    }

    @Test
    fun noSheetMeansNoExitAtAll() {
        assertEquals(
            PendingPaneExit(showAffordance = false, enabled = false),
            pendingPaneExit(PendingSheet.None, actionInProgressIds = emptySet(), bulkRunning = false),
        )
    }
}

private fun reviewExpense(id: Long): Expense = Expense(
    id = id,
    publicId = "pending-$id",
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
