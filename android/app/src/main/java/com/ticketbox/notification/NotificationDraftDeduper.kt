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
     * 去重键以**这条通知的每次投递身份** [notificationKey]（`notificationIdentityKey(sbn.key, sbn.postTime)`
     * 的 hash——同一次投递被重发时不变、两条不同通知或同槽承载的不同事件〔同 sbn.key 但 postTime 变〕必不同）
     * 为**主轴**，而非纯内容。否则"同一分钟、同金额同商户的两笔真账"（连买两杯一样的咖啡 / 给同一人转两次同样
     * 的钱）会撞同一个内容键 → 第二笔被**静默吞掉**（数据丢失）。
     *
     * **有意取舍**：含 `postTime` 故同一次投递的良性重渲染（新 `postTime`：连接刷新 / 分组更新 / OEM 通知刷新 /
     * 再次 `notify()` 终态）会分裂成两条草稿。但 auto-capture 只建**可复核的 pending**（下游"疑似重复"再兜），
     * "宁可多一条可复核草稿、也绝不吞掉一笔真账"是刻意选的较小恶。内容次轴（source/amount/merchant/分钟）此后
     * 主要对 legacy 缺省身份（[notificationKey] 为空）承重。
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
