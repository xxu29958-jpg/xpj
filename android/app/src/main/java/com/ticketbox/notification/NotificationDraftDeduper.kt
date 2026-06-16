package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft

internal class NotificationDraftDeduper(
    private val clockMillis: () -> Long = { System.currentTimeMillis() },
    private val ttlMillis: Long = DEFAULT_TTL_MILLIS,
) {
    private val recentDraftKeys = LinkedHashMap<String, Long>()

    fun tryReserve(draft: NotificationDraft, notificationKey: String): Boolean {
        val now = clockMillis()
        val key = dedupKey(draft, notificationKey)
        synchronized(recentDraftKeys) {
            val iterator = recentDraftKeys.entries.iterator()
            while (iterator.hasNext()) {
                if (now - iterator.next().value > ttlMillis) {
                    iterator.remove()
                }
            }
            if (recentDraftKeys.containsKey(key)) return false
            recentDraftKeys[key] = now
            return true
        }
    }

    fun release(draft: NotificationDraft, notificationKey: String) {
        val key = dedupKey(draft, notificationKey)
        synchronized(recentDraftKeys) {
            recentDraftKeys.remove(key)
        }
    }

    /**
     * 去重键以**通知身份** [notificationKey]（`StatusBarNotification.key`——同一条通知被重发时不变、两条不同的
     * 通知必不同）为**主轴**，而非纯内容。否则"同一分钟、同金额同商户的两笔真账"（连买两杯一样的咖啡 / 给同一人
     * 转两次同样的钱）会撞同一个内容键 → 第二笔被**静默吞掉**（数据丢失）。内容部分（source/amount/merchant/
     * 分钟）作次轴，防个别 App 复用同一通知槽承载不同事件时漏判（同 key 但不同金额仍各记一笔）。
     */
    private fun dedupKey(draft: NotificationDraft, notificationKey: String): String = listOf(
        notificationKey,
        draft.source.apiValue,
        draft.amountCents?.toString().orEmpty(),
        draft.merchant.orEmpty(),
        draft.expenseTime.orEmpty().take(16),
    ).joinToString("|")

    private companion object {
        const val DEFAULT_TTL_MILLIS = 30 * 60 * 1000L
    }
}
