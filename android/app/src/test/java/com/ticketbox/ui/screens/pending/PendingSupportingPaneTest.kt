package com.ticketbox.ui.screens.pending

import com.ticketbox.viewmodel.PendingSheet
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * expanded 宽度下 supporting pane 的内容合同：不渲染第二份死白，
 * 无活动复核时承载真实 triage 内容；有活动复核时复用现有
 * [PendingSheet] 状态把复核提升为常驻面板（不新造 selection/receipt owner）。
 * 非 expanded 宽度不渲染 supporting pane，复核继续走现有 modal sheet。
 */
class PendingSupportingPaneTest {
    @Test
    fun compactWidthKeepsTheActiveReviewInItsModalSheet() {
        assertNull(
            pendingSupportingPaneContent(
                showsSupportingPane = false,
                activeSheet = PendingSheet.BulkConfirm,
            ),
        )
        assertNull(
            pendingSupportingPaneContent(
                showsSupportingPane = false,
                activeSheet = PendingSheet.None,
            ),
        )
    }

    @Test
    fun expandedWidthWithoutAnActiveReviewShowsTheTriagePane() {
        assertEquals(
            PendingSupportingPaneContent.Triage,
            pendingSupportingPaneContent(
                showsSupportingPane = true,
                activeSheet = PendingSheet.None,
            ),
        )
    }

    @Test
    fun expandedWidthWithAnActiveReviewShowsItAsThePersistentPane() {
        assertEquals(
            PendingSupportingPaneContent.Review(PendingSheet.BulkConfirm),
            pendingSupportingPaneContent(
                showsSupportingPane = true,
                activeSheet = PendingSheet.BulkConfirm,
            ),
        )
    }
}
