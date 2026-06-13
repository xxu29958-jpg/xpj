package com.ticketbox.ui.navigation

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
        state.post(LedgerDrillRequest(month = "2026-06", category = "餐饮"))
        assertEquals(
            LedgerDrillRequest(month = "2026-06", category = "餐饮"),
            state.consume(),
        )
        // 取走即清:tab 过场重组再 consume 拿不到旧值,不会重复覆盖用户手改的筛选。
        assertNull(state.consume())
        assertNull(state.pending)
    }

    @Test
    fun secondPostOverwritesUnconsumedFirst() {
        val state = LedgerDrillState()
        state.post(LedgerDrillRequest(month = "2026-06", category = "餐饮"))
        state.post(LedgerDrillRequest(month = "2026-06", category = "交通"))
        assertEquals("交通", state.consume()?.category)
        assertNull(state.consume())
    }
}
