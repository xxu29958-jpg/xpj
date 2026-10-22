package com.ticketbox.notification

import java.time.ZoneId

data class NotificationTimeFragment(val field: String, val literal: String, val label: String)
data class NotificationTimeEvidence(val sourceTimezone: String, val fragments: List<NotificationTimeFragment>, val truncated: Boolean)

/** Extract literals only. The shared server parser resolves dates, ambiguity and roles. */
internal object NotificationTimeExtractor {
    private const val CLOCK = """(?:(?:上午|下午|晚上)\s*)?\d{1,2}[时:：]\d{2}(?:(?:[:：]|分)\d{2}秒?|分)?(?:\s*(?:AM|PM))?(?:\s*(?:Z|(?:UTC|GMT)?[+-][\d:]+|UTC|GMT|CST|EST|PST))?"""
    private const val DATE = """(?:\d{4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{1,2}[\s/-]+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[\s/-]+\d{4}|\d{1,2}月\d{1,2}日|今天|今日|昨天|昨日)"""
    private val timestamp = Regex("""(?<!\d)(?:$DATE(?:[T\s]*(?:时间\s*[:：]?\s*)?$CLOCK)?|$CLOCK)(?!\d)""", RegexOption.IGNORE_CASE)
    private val labels = Regex("""支付时间|付款时间|支付日期|付款日期|还款时间|还款日期|交易时间|交易日期|成交时间|消费时间|消费日期|扣款时间|退款时间|退款日期|退回时间|下单时间|订单时间|下单日期|创建时间|开票日期|出票时间|打印时间|打印日期|重打时间|截图时间|截图日期|接收时间|通知时间|来电时间|预计扣款|将于|应还日期|到期时间|到期日期|PAID AT|PAYMENT TIME|TRANSACTION TIME|TRANSACTION DATE|REFUND TIME|ORDER TIME|ISSUED AT|PRINTED AT|PRINT TIME|CAPTURED AT|RECEIVED AT|DUE DATE""", RegexOption.IGNORE_CASE)

    fun read(fields: List<Pair<String, String>>, zone: String = ZoneId.systemDefault().id): NotificationTimeEvidence {
        val evidence = fields.flatMap { (field, text) ->
            timestamp.findAll(text).mapNotNull { match ->
                val prefix = text.substring(maxOf(0, match.range.first - 40), match.range.first)
                val label = labels.findAll(prefix).lastOrNull()?.takeIf {
                    prefix.substring(it.range.last + 1).all { char -> char.isWhitespace() || char in ":：" }
                }?.value.orEmpty()
                // An unlabelled status-bar clock has no transaction date.
                if (label.isEmpty() && !Regex(DATE, RegexOption.IGNORE_CASE).containsMatchIn(match.value)) null
                else NotificationTimeFragment(field, match.value.trim(), label)
            }.toList()
        }.distinct()
        val bounded = evidence.filter { it.literal.length <= 80 }.take(8)
        return NotificationTimeEvidence(zone, bounded, evidence.size != bounded.size)
    }
}
