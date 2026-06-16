package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant

data class PaymentNotificationSnapshot(
    val packageName: String,
    val title: String?,
    val text: String?,
    val bigText: String?,
    val subText: String?,
    val postTimeMillis: Long,
)

object PaymentNotificationParser {
    private val currencyBeforeAmount = Regex(
        """(?:￥|¥|人民币|RMB|CNY)\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)""",
        RegexOption.IGNORE_CASE,
    )
    private val yuanAfterAmount = Regex(
        """([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)\s*元""",
    )
    private val merchantPatterns = listOf(
        Regex("""(?:付款给|支付给|商家|商户|收款方|交易商户|对方户名)[:：\s]*([^，,。；;\n￥¥]{2,40})"""),
        Regex("""(?:在|于)([^，,。；;\n￥¥]{2,40})(?:消费|支出|付款|支付)"""),
    )
    private val bankContext = Regex("""(银行|信用卡|储蓄账户|尾号|动账|交易|支出人民币|消费人民币)""")
    private val expenseWords = Regex("""(付款成功|成功付款|已成功付款|支付成功|已支付|消费|支出|扣款|交易成功|支出人民币|消费人民币)""")
    private val incomeOrRefundWords = Regex("""(收款(?!方)|到账|收入|转入|退款|退回|红包)""")
    private val genericTitleWords = Regex("""(微信支付|支付宝|银行|通知|交易提醒|动账提醒|服务通知)""")
    private val weChatPackages = setOf("com.tencent.mm")
    private val alipayPackages = setOf("com.eg.android.alipaygphone")
    private val smsPackages = setOf(
        "com.android.mms",
        "com.android.messaging",
        "com.google.android.apps.messaging",
        "com.samsung.android.messaging",
    )

    fun parse(snapshot: PaymentNotificationSnapshot): NotificationDraft? {
        // 隐私 + 洁癖：**先按包名过滤**。非白名单（微信 / 支付宝 / 短信）的通知，连正文都不读——否则下面的
        // income/expense 正则会扫**每一条通知（任何 App）的正文内容**才决定丢弃。候选判定单列成
        // [isCandidatePackage]，可单测、把白名单文档化（注：京东白条 `com.jingdong.app.mall` 不在内=已知盲区）。
        if (!isCandidatePackage(snapshot.packageName)) return null
        val joined = snapshot.joinedText()
        if (joined.isBlank()) return null
        if (incomeOrRefundWords.containsMatchIn(joined)) return null
        if (!expenseWords.containsMatchIn(joined)) return null

        val source = resolveSource(snapshot.packageName, joined) ?: return null
        val amountCents = parseAmountCents(joined) ?: return null
        val merchant = parseMerchant(snapshot, joined)
        return NotificationDraft(
            source = source,
            amountCents = amountCents,
            merchant = merchant,
            category = null,
            expenseTime = Instant.ofEpochMilli(snapshot.postTimeMillis).toString(),
        )
    }

    /**
     * 包名是否在白名单内（=值不值得读这条通知的正文）。微信 / 支付宝 / 短信类才算候选；其余（新闻、聊天、
     * 随便哪个 App）一律否，正文连看都不看。单列成 `internal` 以便单测钉死白名单边界。SMS 侧的进一步细分
     * （需含 bankContext 才落 BankSms）仍在 [resolveSource]——本判定只做"要不要看正文"这一层粗过滤。
     */
    internal fun isCandidatePackage(packageName: String): Boolean {
        val pkg = packageName.lowercase()
        return pkg in weChatPackages || pkg in alipayPackages || isSmsPackage(pkg)
    }

    private fun resolveSource(packageName: String, text: String): NotificationDraftSource? {
        val normalizedPackage = packageName.lowercase()
        return when {
            normalizedPackage in weChatPackages -> {
                NotificationDraftSource.WeChat
            }
            normalizedPackage in alipayPackages -> {
                NotificationDraftSource.Alipay
            }
            isSmsPackage(normalizedPackage) -> {
                if (bankContext.containsMatchIn(text)) NotificationDraftSource.BankSms else null
            }
            else -> null
        }
    }

    private fun isSmsPackage(packageName: String): Boolean =
        packageName in smsPackages ||
            packageName.contains(".mms") ||
            packageName.contains(".sms") ||
            packageName.contains("messaging")

    private fun parseAmountCents(text: String): Long? {
        val amount = currencyBeforeAmount.find(text)?.groupValues?.getOrNull(1)
            ?: yuanAfterAmount.find(text)?.groupValues?.getOrNull(1)
            ?: return null
        val decimal = amount.replace(",", "").toBigDecimalOrNull() ?: return null
        return runCatching {
            decimal
                .multiply(BigDecimal(100))
                .setScale(0, RoundingMode.HALF_UP)
                .longValueExact()
        }.getOrNull()
    }

    private fun parseMerchant(snapshot: PaymentNotificationSnapshot, text: String): String? {
        for (pattern in merchantPatterns) {
            val candidate = pattern.find(text)?.groupValues?.getOrNull(1)
            cleanMerchant(candidate)?.let { return it }
        }
        return cleanMerchant(snapshot.title)
            ?.takeUnless { genericTitleWords.containsMatchIn(it) }
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

    private fun PaymentNotificationSnapshot.joinedText(): String =
        listOf(title, text, bigText, subText)
            .mapNotNull { it?.trim()?.takeIf(String::isNotBlank) }
            .distinct()
            .joinToString(separator = "\n")
}
