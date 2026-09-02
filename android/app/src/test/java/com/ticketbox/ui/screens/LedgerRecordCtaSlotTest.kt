package com.ticketbox.ui.screens

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * W2-B: 「记一笔」命令的单一槽位（承 W2-A pendingUploadEntrySlot 纪律）——
 * 任一屏幕态最多一个记一笔入口：有内容/首次同步中/有筛选的空态都在页头
 * （记录命令不依赖列表可读），仅无筛选的 settled 空态把入口让给空态卡；
 * Viewer 没有任何写命令入口（只读投影诚实）。
 */
class LedgerRecordCtaSlotTest {

    @Test
    fun contentKeepsCtaInHeader() {
        assertEquals(
            LedgerRecordCtaSlot.Header,
            ledgerRecordCtaSlot(
                readOnly = false,
                hasItems = true,
                isFirstSync = false,
                hasFilters = false,
            ),
        )
    }

    @Test
    fun settledUnfilteredEmptyMovesCtaToEmptyState() {
        assertEquals(
            LedgerRecordCtaSlot.EmptyState,
            ledgerRecordCtaSlot(
                readOnly = false,
                hasItems = false,
                isFirstSync = false,
                hasFilters = false,
            ),
        )
    }

    @Test
    fun filteredEmptyKeepsCtaInHeader() {
        assertEquals(
            LedgerRecordCtaSlot.Header,
            ledgerRecordCtaSlot(
                readOnly = false,
                hasItems = false,
                isFirstSync = false,
                hasFilters = true,
            ),
        )
    }

    @Test
    fun firstSyncKeepsCtaInHeader() {
        assertEquals(
            LedgerRecordCtaSlot.Header,
            ledgerRecordCtaSlot(
                readOnly = false,
                hasItems = false,
                isFirstSync = true,
                hasFilters = false,
            ),
        )
    }

    @Test
    fun viewerHasNoCtaAnywhere() {
        assertNull(
            ledgerRecordCtaSlot(
                readOnly = true,
                hasItems = true,
                isFirstSync = false,
                hasFilters = false,
            ),
        )
        assertNull(
            ledgerRecordCtaSlot(
                readOnly = true,
                hasItems = false,
                isFirstSync = false,
                hasFilters = false,
            ),
        )
    }
}
