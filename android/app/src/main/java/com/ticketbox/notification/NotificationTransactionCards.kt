package com.ticketbox.notification

/** Split only explicit event containers; payment/balance/discount fields within one card stay together. */
internal object NotificationTransactionCards {
    private val heading = Regex("""(?m)^(?:交易提醒|支付成功|付款成功|交易成功|扣款成功)(?=[\s:：]|${'$'})""")
    private val spend = Regex("""你有一笔[^\n。；;]*?(?:元|￥|¥)[^\n。；;]*?(?:支出|消费)""")

    fun read(snapshot: PaymentNotificationSnapshot): List<String> {
        if (snapshot.textLines.isNotEmpty()) return snapshot.textLines // Keep identity through single-to-InboxStyle transitions.
        for (text in listOfNotNull(snapshot.bigText, snapshot.text)) {
            val starts = heading.findAll(text).map { it.range.first }.toList()
            if (starts.size > 1) return starts.mapIndexed { index, start ->
                text.substring(start, starts.getOrElse(index + 1) { text.length })
            }
            val spends = spend.findAll(text).toList()
            if (spends.size > 1) return spends.mapIndexed { index, match ->
                text.substring(match.range.first, spends.getOrNull(index + 1)?.range?.first ?: text.length)
            }
        }
        return emptyList()
    }
}
