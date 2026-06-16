package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class NotificationDraftDeduperTest {
    @Test
    fun failedDraftCanBeRetriedImmediately() {
        var now = 1_000L
        val deduper = NotificationDraftDeduper(clockMillis = { now }, ttlMillis = 30 * 60 * 1000L)
        val draft = draft()

        assertTrue(deduper.tryReserve(draft, "n-1"))
        assertFalse(deduper.tryReserve(draft, "n-1")) // same notification re-posted → deduped

        deduper.release(draft, "n-1")

        assertTrue(deduper.tryReserve(draft, "n-1"))
    }

    @Test
    fun sameNotificationSuppressesDuplicatesUntilTtlExpires() {
        var now = 1_000L
        val deduper = NotificationDraftDeduper(clockMillis = { now }, ttlMillis = 10L)
        val draft = draft()

        assertTrue(deduper.tryReserve(draft, "n-1"))
        assertFalse(deduper.tryReserve(draft, "n-1"))

        now += 11L

        assertTrue(deduper.tryReserve(draft, "n-1"))
    }

    @Test
    fun distinctNotificationsWithIdenticalContentAreNotDeduped() {
        // 反向覆盖（修"静默吞真账"）：同一分钟、同金额同商户的两笔**真账**是两条不同的系统通知（sbn.key 不同），
        // 必须各记一笔——绝不能因内容相同被去重吞掉。旧版按内容去重时这里的第二次 tryReserve 会返 false。
        val deduper = NotificationDraftDeduper(clockMillis = { 1_000L }, ttlMillis = 30 * 60 * 1000L)
        val draft = draft()

        assertTrue(deduper.tryReserve(draft, "n-1"))
        assertTrue(deduper.tryReserve(draft, "n-2")) // 不同通知身份 → 不去重 → 两笔都留
    }

    private fun draft(): NotificationDraft = NotificationDraft(
        source = NotificationDraftSource.WeChat,
        amountCents = 2580L,
        merchant = "星巴克",
        category = null,
        expenseTime = "2026-05-13T08:00:00Z",
    )
}
