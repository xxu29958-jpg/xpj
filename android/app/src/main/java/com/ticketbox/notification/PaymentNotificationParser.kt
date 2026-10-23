package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
import java.time.Instant

data class PaymentNotificationSnapshot(
    val packageName: String,
    val title: String?,
    val text: String?,
    val bigText: String?,
    val subText: String?,
    val postTimeMillis: Long,
)

/** Parsed evidence only. Raw notification bodies and the system key stay on the device. */
data class NotificationEvidence(val kind: String, val amountMinor: Long?, val field: String, val evidence: String)

sealed interface PaymentNotificationResult {
    val candidates: List<NotificationEvidence>
    val timeEvidence: NotificationTimeEvidence?
    val fieldEvidence: NotificationFieldEvidence?
    data class Expense(val draft: NotificationDraft,
        override val candidates: List<NotificationEvidence> = emptyList(),
        override val timeEvidence: NotificationTimeEvidence? = null,
        val capturedAt: String? = draft.expenseTime,
        override val fieldEvidence: NotificationFieldEvidence? = null) : PaymentNotificationResult
    data class Repayment(val draft: RepaymentNotificationDraft,
        override val candidates: List<NotificationEvidence> = emptyList(),
        override val timeEvidence: NotificationTimeEvidence? = null,
        override val fieldEvidence: NotificationFieldEvidence? = null) : PaymentNotificationResult
    data class Review(val source: String, val capturedAt: String, val merchant: String?,
        override val candidates: List<NotificationEvidence>,
        override val timeEvidence: NotificationTimeEvidence? = null,
        override val fieldEvidence: NotificationFieldEvidence? = null) : PaymentNotificationResult
}

object PaymentNotificationParser {
    const val VERSION = "transaction-evidence-v4"
    private val bankContext = Regex("""(银行|信用卡|储蓄账户|尾号|动账|交易|支出人民币|消费人民币)""")
    private val sources = mapOf("com.tencent.mm" to "wechat", "com.eg.android.alipaygphone" to "alipay",
        "com.jingdong.app.mall" to "jd", "com.jd.jrapp" to "jd", "com.sankuai.meituan" to "meituan")
    internal fun isCandidatePackage(packageName: String): Boolean {
        val pkg = packageName.lowercase()
        // Keep SMS-family admission shared by the listener and parser; bank/transaction evidence is checked below.
        return pkg in sources || pkg.contains(".sms") || pkg.contains(".mms") || pkg.contains("messaging")
    }

    fun parse(snapshot: PaymentNotificationSnapshot): PaymentNotificationResult? {
        if (!isCandidatePackage(snapshot.packageName)) return null
        val fields = listOf("title" to snapshot.title, "text" to snapshot.text,
            "bigText" to snapshot.bigText, "subText" to snapshot.subText)
            .mapNotNull { (name, value) -> value?.trim()?.takeIf { it.isNotEmpty() }?.let { name to it } }
            .distinctBy { it.second }
        val joined = fields.joinToString("\n") { it.second }
        val source = sources[snapshot.packageName.lowercase()]
            ?: if (bankContext.containsMatchIn(joined)) "bank_sms" else return null
        val evidence = fields.flatMap { (field, value) -> NotificationTransactionEvidence.read(field, value) }.distinct()
        val candidates = evidence.take(24)
        val financial = evidence.filter { it.kind in setOf("expense", "repayment") }
        if (financial.isEmpty()) return null // pure reminder, marketing, income or refund
        val amounts = financial.filter { it.amountMinor != null }.distinctBy { it.kind to it.amountMinor }
        val conflict = evidence.size > 24 || evidence.any { it.kind == "refund" } || amounts.size != 1 ||
            financial.any { it.kind != amounts.singleOrNull()?.kind }
        val time = Instant.ofEpochMilli(snapshot.postTimeMillis).toString()
        val timeEvidence = NotificationTimeExtractor.read(fields)
        val fieldEvidence = PaymentNotificationFields.fieldEvidence(fields)
        if (conflict) return PaymentNotificationResult.Review(source, time,
            PaymentNotificationFields.parseMerchant(snapshot, joined), candidates, timeEvidence, fieldEvidence)
        val chosen = amounts.single()
        return if (chosen.kind == "repayment") PaymentNotificationResult.Repayment(
            RepaymentNotificationDraft(RepaymentDraftSource.entries.single { it.apiValue == source },
                requireNotNull(chosen.amountMinor), PaymentNotificationFields.parseRepaymentLabel(joined), time), candidates, timeEvidence, fieldEvidence)
        else PaymentNotificationResult.Expense(
            NotificationDraft(NotificationDraftSource.entries.single { it.apiValue == source },
                requireNotNull(chosen.amountMinor), PaymentNotificationFields.parseMerchant(snapshot, joined), null, null),
            candidates, timeEvidence, capturedAt = time, fieldEvidence = fieldEvidence)
    }
}

/** Metadata is read from the original fields, including card tails in reminder clauses. */
private object PaymentNotificationFields {
    private val currencyBeforeAmount = Regex(
        """(?:￥|¥|人民币|RMB|CNY)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)""",
        RegexOption.IGNORE_CASE,
    )
    private val yuanAfterAmount = Regex(
        """([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*元""",
    )
    private val merchantPatterns = listOf(
        Regex("""(?:付款给|支付给|商家|商户|收款方|交易商户|对方户名)[:：\s]*([^，,。；;\n￥¥]{2,40})"""),
        Regex("""(?:在|于)([^，,。；;\n￥¥]{2,40})(?:消费|支出|付款|支付)"""),
    )
    private val genericTitleWords = Regex("""(微信支付|支付宝|银行|通知|交易提醒|动账提醒|服务通知)""")
    // 还款标签:卡尾号 / 平台名(花呗 / 借呗 / 白条 / 美团月付),用于 ③b 模糊匹配与展示,可为空。
    private val cardTailPattern = Regex("""尾号\s*([0-9]{4})""")
    private val repaymentPlatformPattern = Regex("""(花呗|借呗|白条|美团月付|月付|信用卡)""")
    fun parseMerchant(snapshot: PaymentNotificationSnapshot, text: String): String? {
        for (pattern in merchantPatterns) {
            val candidate = pattern.find(text)?.groupValues?.getOrNull(1)
            cleanMerchant(candidate)?.let { return it }
        }
        return cleanMerchant(snapshot.title)
            ?.takeUnless { genericTitleWords.containsMatchIn(it) }
    }

    fun fieldEvidence(fields: List<Pair<String, String>>): NotificationFieldEvidence {
        val fragments = fields.flatMap { (field, text) ->
            val snippets = NotificationTransactionEvidence.fieldFragments(field, text).toMutableList()
            val matches = merchantPatterns.flatMap { it.findAll(text).toList() }
            snippets += matches.map { NotificationFieldFragment(field, it.value) }
            if (matches.isEmpty() && field == "title" && cleanMerchant(text) != null && !genericTitleWords.containsMatchIn(text)) {
                snippets += NotificationFieldFragment(field, text)
            }
            snippets.sortedBy { text.indexOf(it.literal) }
        }
        val distinct = fragments.distinct()
        return NotificationFieldEvidence(distinct.filter { it.literal.length <= 96 }.take(24),
            truncated = distinct.size > 24 || distinct.any { it.literal.length > 96 })
    }

    /** 还款标签:优先卡尾号(尾号1234),否则平台名(花呗 / 借呗 / 白条 / 美团月付 / 信用卡);都没有则 null。 */
    fun parseRepaymentLabel(text: String): String? {
        cardTailPattern.find(text)?.groupValues?.getOrNull(1)?.let { return "尾号$it" }
        return repaymentPlatformPattern.find(text)?.value
    }

    private fun cleanMerchant(value: String?): String? {
        val cleaned = value
            ?.replace(currencyBeforeAmount, "")
            ?.replace(yuanAfterAmount, "")
            ?.replace(Regex("""(付款|支付|成功|消费|支出|人民币|交易|商户|收款方)"""), "")
            ?.trim(' ', '\t', '\n', '\r', ':', '：', ',', '，', '.', '。', ';', '；')
            ?.take(40)
            ?.trim()
        return cleaned?.takeIf { it.length >= 2 }
    }
}
