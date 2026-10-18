package com.ticketbox.notification

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor

/** Bind money to its local semantic label before choosing a transaction type. */
internal object NotificationTransactionEvidence {
    private val amount = Regex(
        """(?:￥|¥|人民币|RMB|CNY)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?:\s*元)?|([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*元""",
        RegexOption.IGNORE_CASE,
    )
    // Decimal points and thousands separators belong to the amount, not a clause boundary.
    private val boundary = Regex("""[，。；;\n]|(?<!\d)[,.]|[,.](?!\d)""")
    private val label = Regex(
        """实付|实际支付|实际付款|支付金额|付款金额|消费金额|还款成功|已还款|还款完成|已还清|偿还成功|还款入账|自动还款|主动还款|代扣还款|还款|偿还|还入|归还欠款|付款成功|成功付款|已成功付款|支付成功|已支付|消费|支出|扣款|交易成功|退款|退回|余额|额度|红包|优惠|订单金额|账单|应还|收款(?!方)|收入|转入""",
    )
    private val auxiliary = Regex("""余额|额度|红包|优惠|订单金额|账单|应还|收款|收入|转入""")
    private val repayment = Regex("""还款|偿还|还入|还清|归还欠款""")
    private val reminder = Regex("""待|应|需|请[^，。；;]{0,18}|尽快|即将|计划|尚未|未|还款日|到期|失败""")
    private val bridge = Regex("""^(?:的|已|成功|人民币|金额|本期|合计|为|共|[:：\s])*${'$'}""")
    private val repaymentDebit = Regex("""(?:还款|偿还)(?:自动|银行|已|成功|代扣|[:：\s])*${'$'}""")

    private data class Anchor(val match: MatchResult, val kind: String)
    private data class Clause(val text: String, val anchors: List<Anchor>, val money: List<MatchResult>)

    fun read(field: String, text: String): List<NotificationEvidence> {
        val clauses = boundary.split(text).filter { it.isNotBlank() }.map { value ->
            Clause(value, label.findAll(value).map { Anchor(it, kind(value, it)) }.toList(), amount.findAll(value).toList())
        }
        val result = clauses.flatMap { clause ->
            clause.money.mapNotNull { money -> bind(clause, money)?.let { anchor ->
                NotificationEvidence(anchor.kind, minor(money), field, "amount_bound_${anchor.kind}")
            } }
        }.toMutableList()
        val events = clauses.flatMap { it.anchors }.filter { it.kind in setOf("expense", "repayment", "refund") }
        // A heading such as "还款成功" can introduce a single unlabeled amount in the
        // next clause. Balance, bill, discount and income amounts are never eligible.
        val unbound = clauses.flatMap { clause -> clause.money.filter { bind(clause, it) == null } }
        if (result.none { it.kind in setOf("expense", "repayment") } &&
            events.map { it.kind }.distinct().size == 1 && unbound.size == 1) {
            result += NotificationEvidence(events.first().kind, minor(unbound.single()), field, "single_amount_after_event")
        }
        events.map { it.kind }.distinct().filter { kind -> result.none { it.kind == kind } }.forEach { kind ->
            result += NotificationEvidence(kind, null, field, "event_without_bound_amount")
        }
        return result.filter { it.kind != "auxiliary" }.distinct()
    }

    private fun bind(clause: Clause, money: MatchResult): Anchor? {
        val previousMoney = clause.money.lastOrNull { it.range.last < money.range.first }?.range?.last ?: -1
        val nextMoney = clause.money.firstOrNull { it.range.first > money.range.last }?.range?.first ?: clause.text.length
        val before = clause.anchors.lastOrNull { it.match.range.last < money.range.first && it.match.range.first > previousMoney }
        val after = clause.anchors.firstOrNull { it.match.range.first > money.range.last && it.match.range.last < nextMoney }
        // Direct "37.90元的支出" is as strong as "支出37.90元". A prior nearby label
        // wins a tie, so "账单1288已还款500" cannot attach 1288 to the next event.
        val beforeGap = before?.let { clause.text.substring(it.match.range.last + 1, money.range.first) }
        val afterGap = after?.let { clause.text.substring(money.range.last + 1, it.match.range.first) }
        return when {
            beforeGap != null && bridge.matches(beforeGap) -> before
            afterGap != null && bridge.matches(afterGap) -> after
            before != null && beforeGap!!.length <= 40 -> before
            else -> null
        }
    }

    private fun kind(text: String, match: MatchResult): String {
        if (auxiliary.matches(match.value)) return "auxiliary"
        if (match.value in setOf("退款", "退回")) return "refund"
        val before = text.substring(0, match.range.first)
        val tail = text.substring(match.range.last + 1)
        if (reminder.containsMatchIn(before.takeLast(18)) || tail.startsWith("日") ||
            tail.startsWith("失败") || tail.startsWith("提醒")) return "auxiliary"
        // The debit in "自动还款扣款1200元" is the mechanism of that repayment,
        // not a second purchase elsewhere in the notification.
        if (match.value == "扣款" && repaymentDebit.containsMatchIn(before)) return "repayment"
        return if (repayment.containsMatchIn(match.value)) "repayment" else "expense"
    }

    private fun minor(match: MatchResult): Long? = parseExactMoneyMinor(
        match.groupValues.drop(1).first { it.isNotEmpty() }.replace(",", ""), CurrencyCode.CNY,
    )?.takeIf { it > 0 }
}
