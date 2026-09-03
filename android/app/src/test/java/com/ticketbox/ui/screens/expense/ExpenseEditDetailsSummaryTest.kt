package com.ticketbox.ui.screens.expense

import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * 明细/拆账折叠行的摘要映射：折叠只是把详细面板收成一行，状态语义与
 * [expenseDetailPanelPresentation] 完全一致——未加载/加载中绝不声明「还没有」，
 * 失败绝不压成 0 条，只有 Loaded 空模型才是真实空。
 */
internal class ExpenseEditDetailsSummaryTest {

    @Test
    fun unresolvedOrLoadingNeverDeclaresEmpty() {
        listOf(
            ExpenseDetailDataLoadState.Unknown,
            ExpenseDetailDataLoadState.Loading,
        ).forEach { loadState ->
            assertEquals(
                ExpenseDetailRowKind.Loading,
                expenseDetailCollapsedRowKind(
                    loading = false,
                    loadState = loadState,
                    rowCount = null,
                ),
                "loadState=$loadState must render as loading, never empty",
            )
        }
        assertEquals(
            ExpenseDetailRowKind.Loading,
            expenseDetailCollapsedRowKind(
                loading = true,
                loadState = ExpenseDetailDataLoadState.Loaded,
                rowCount = 0,
            ),
        )
    }

    @Test
    fun failureNeverCollapsesToZeroRows() {
        assertEquals(
            ExpenseDetailRowKind.Failed,
            expenseDetailCollapsedRowKind(
                loading = false,
                loadState = ExpenseDetailDataLoadState.Failed,
                rowCount = null,
            ),
        )
        // Loaded 却没有模型（防御分支）：既不是真实空也不是行数，按失败呈现，
        // 展开后由既有 message slot 说明。
        assertEquals(
            ExpenseDetailRowKind.Failed,
            expenseDetailCollapsedRowKind(
                loading = false,
                loadState = ExpenseDetailDataLoadState.Loaded,
                rowCount = null,
            ),
        )
    }

    @Test
    fun loadedEmptyIsHonestEmpty() {
        assertEquals(
            ExpenseDetailRowKind.Empty,
            expenseDetailCollapsedRowKind(
                loading = false,
                loadState = ExpenseDetailDataLoadState.Loaded,
                rowCount = 0,
            ),
        )
    }

    @Test
    fun loadedRowsShowRowCount() {
        assertEquals(
            ExpenseDetailRowKind.Rows,
            expenseDetailCollapsedRowKind(
                loading = false,
                loadState = ExpenseDetailDataLoadState.Loaded,
                rowCount = 3,
            ),
        )
    }

    @Test
    fun mismatchDefaultsExpandedOnlyWhileUnacknowledged() {
        assertTrue(expenseDetailDefaultsExpanded(mismatchKnown = true, mismatchAcknowledged = false))
        assertFalse(expenseDetailDefaultsExpanded(mismatchKnown = true, mismatchAcknowledged = true))
        assertFalse(expenseDetailDefaultsExpanded(mismatchKnown = false, mismatchAcknowledged = false))
    }
}
