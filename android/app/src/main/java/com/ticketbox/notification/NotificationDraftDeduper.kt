package com.ticketbox.notification

internal class NotificationDraftDeduper(
    private val clockMillis: () -> Long = { System.currentTimeMillis() },
    private val ttlMillis: Long = DEFAULT_TTL_MILLIS,
) {
    private val recentDraftKeys = LinkedHashMap<String, Long>()

    fun tryReserve(result: PaymentNotificationResult, notificationKey: String): Boolean {
        val now = clockMillis()
        val key = dedupKey(result, notificationKey)
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

    fun release(result: PaymentNotificationResult, notificationKey: String) {
        val key = dedupKey(result, notificationKey)
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
     * 消费 / 还款两类草稿共用同一去重器（一条通知只分类成其一，见 [PaymentNotificationResult]），故键里带
     * 类型前缀（`expense` / `repayment`）防跨类型碰撞，再叠内容次轴（source/amount/label/分钟）。
     *
     * **有意取舍**：含 `postTime` 故同一次投递的良性重渲染（新 `postTime`：连接刷新 / 分组更新 / OEM 通知刷新 /
     * 再次 `notify()` 终态）会分裂成两条草稿。但 auto-capture 只建**可复核的 pending**（下游"疑似重复"再兜），
     * "宁可多一条可复核草稿、也绝不吞掉一笔真账"是刻意选的较小恶。内容次轴此后主要对 legacy 缺省身份
     * （[notificationKey] 为空）承重。
     */
    private fun dedupKey(result: PaymentNotificationResult, notificationKey: String): String = when (result) {
        is PaymentNotificationResult.Expense -> listOf(
            notificationKey,
            "expense",
            result.draft.source.apiValue,
            result.draft.amountCents?.toString().orEmpty(),
            result.draft.merchant.orEmpty(),
            result.draft.expenseTime.orEmpty().take(16),
        ).joinToString("|")

        is PaymentNotificationResult.Repayment -> listOf(
            notificationKey,
            "repayment",
            result.draft.source.apiValue,
            result.draft.amountCents.toString(),
            result.draft.merchantLabel.orEmpty(),
            result.draft.capturedAt.orEmpty().take(16),
        ).joinToString("|")
    }

    private companion object {
        const val DEFAULT_TTL_MILLIS = 30 * 60 * 1000L
    }
}
