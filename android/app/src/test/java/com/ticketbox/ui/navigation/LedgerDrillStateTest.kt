package com.ticketbox.ui.navigation

import com.ticketbox.viewmodel.LedgerDataQualityFilter
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * [LedgerDrillState] 单槽 post/consume 契约(§三报表钻取,镜像 LaunchActionState 形态):
 * consume 取走即清(Route 重入不重复触发);连 post 后者覆盖(目标页只有一套筛选)。
 */
class LedgerDrillStateTest {

    @Test
    fun consumeTakesPendingRequestExactlyOnce() {
        val state = LedgerDrillState()
        state.post(LedgerDrillRequest.Category(month = "2026-06", category = "餐饮"))
        assertEquals(
            LedgerDrillRequest.Category(month = "2026-06", category = "餐饮"),
            state.consume(),
        )
        // 取走即清:tab 过场重组再 consume 拿不到旧值,不会重复覆盖用户手改的筛选。
        assertNull(state.consume())
        assertNull(state.pending)
    }

    @Test
    fun secondPostOverwritesUnconsumedFirst() {
        val state = LedgerDrillState()
        state.post(LedgerDrillRequest.Category(month = "2026-06", category = "餐饮"))
        state.post(LedgerDrillRequest.Category(month = "2026-06", category = "交通"))
        val consumed = state.consume() as LedgerDrillRequest.Category
        assertEquals("交通", consumed.category)
        assertNull(state.consume())
    }

    @Test
    fun dataQualityRequestKeepsItsTypedFilter() {
        val state = LedgerDrillState()
        state.post(
            LedgerDrillRequest.DataQuality(LedgerDataQualityFilter.ConfirmedWithoutImage),
        )

        assertEquals(
            LedgerDrillRequest.DataQuality(LedgerDataQualityFilter.ConfirmedWithoutImage),
            state.consume(),
        )
        assertNull(state.pending)
    }
}
