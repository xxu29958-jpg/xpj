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

    @Test
    fun slotReuseWithNewPostTimeSplitsButSamePostTimeDedupes() {
        // codex PR#20 P2#1 端到端(单元级)：用真实的 notificationIdentityKey 生成身份,把 identity 函数与去重器接起来。
        // 同一通知槽(同 sbn.key)的两笔真账 postTime 不同 → 两个不同身份 → 各 reserve;同一次投递(同 key 同 postTime)
        // 重发 → 同身份 → 去重。锁住"同槽不同事件分裂 AND 同一投递去重"的组合性质(此前只在后端测过)。
        val deduper = NotificationDraftDeduper(clockMillis = { 1_000L }, ttlMillis = 30 * 60 * 1000L)
        val draft = draft()
        val firstPayment = notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_000_000L)
        val secondPayment = notificationIdentityKey("0|com.tencent.mm|7|null|10", 1_700_000_060_000L)

        assertTrue(deduper.tryReserve(draft, firstPayment))
        assertTrue(deduper.tryReserve(draft, secondPayment)) // 同槽新事件(新 postTime) → 各记一笔
        assertFalse(deduper.tryReserve(draft, firstPayment)) // 同一次投递重发(同身份) → 去重
    }

    private fun draft(): NotificationDraft = NotificationDraft(
        source = NotificationDraftSource.WeChat,
        amountCents = 2580L,
        merchant = "星巴克",
        category = null,
        expenseTime = "2026-05-13T08:00:00Z",
    )
}
