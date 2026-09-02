package com.ticketbox.ui.screens.pending

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * 上传入口的唯一性合同：任一屏幕态最多一个「上传小票」入口。
 * 上传命令不依赖列表 query 成功——Loading/LoadFailed 仍保留页头入口，
 * 不得因列表暂不可读夺走上传能力；只有 settled 空队列把入口落到空态卡；
 * 只读角色任何屏幕态都没有入口。
 */
class PendingUploadEntryTest {
    @Test
    fun contentQueueOffersItsSingleUploadEntryInTheHeader() {
        assertEquals(
            PendingUploadEntrySlot.Header,
            pendingUploadEntrySlot(bodyState = PendingListBodyState.Content, readOnly = false),
        )
    }

    @Test
    fun settledEmptyQueueOffersItsSingleUploadEntryInTheEmptyState() {
        assertEquals(
            PendingUploadEntrySlot.EmptyState,
            pendingUploadEntrySlot(bodyState = PendingListBodyState.Empty, readOnly = false),
        )
    }

    @Test
    fun loadingAndFailedQueuesKeepTheHeaderEntry() {
        assertEquals(
            PendingUploadEntrySlot.Header,
            pendingUploadEntrySlot(bodyState = PendingListBodyState.Loading, readOnly = false),
        )
        assertEquals(
            PendingUploadEntrySlot.Header,
            pendingUploadEntrySlot(bodyState = PendingListBodyState.LoadFailed, readOnly = false),
        )
    }

    @Test
    fun readOnlyQueueHasNoUploadEntryInAnyBodyState() {
        PendingListBodyState.entries.forEach { bodyState ->
            assertNull(pendingUploadEntrySlot(bodyState = bodyState, readOnly = true))
        }
    }
}
