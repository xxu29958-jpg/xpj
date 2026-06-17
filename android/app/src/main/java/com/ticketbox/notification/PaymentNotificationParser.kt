package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
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

/**
 * ADR-0049 §杠杆③ — 一条候选支付通知被分类成的结果（消费 vs 还款 vs 忽略）。
 *
 * 一条通知只分类一次（[PaymentNotificationParser.parse] 是统一分类器）：消费 → [Expense] 落
 * 支出 pending 草稿（既有路径，§通知闭环）；还款 → [Repayment] 落**还款** pending 草稿
 * （新路径，走 `/api/repayment-drafts`，§8 永不自动记账）；提醒 / 收款 / 退款 / 不可解析 → `null`
 * 被忽略。把「消费 vs 还款」拆成不同结果类型，是修「信用卡还款被误当新支出重复计」双计 bug 的关键：
 * 还款分类**优先于**消费，含「还款 / 偿还」的通知绝不再落支出草稿。
 */
sealed interface PaymentNotificationResult {
    data class Expense(val draft: NotificationDraft) : PaymentNotificationResult

    data class Repayment(val draft: RepaymentNotificationDraft) : PaymentNotificationResult
}

object PaymentNotificationParser {
    private val bankContext = Regex("""(银行|信用卡|储蓄账户|尾号|动账|交易|支出人民币|消费人民币)""")
    private val expenseWords = Regex("""(付款成功|成功付款|已成功付款|支付成功|已支付|消费|支出|扣款|交易成功|支出人民币|消费人民币)""")
    private val incomeOrRefundWords = Regex("""(收款(?!方)|到账|收入|转入|退款|退回|红包)""")
    // 还款**已完成**信号:命中即判还款,**优先于**消费/提醒(修双计——「自动还款扣款¥X成功」含「扣款」过去被
    // 误判支出;现「自动还款」属还款已完成,先于 expenseWords 命中)。
    private val repaymentDoneWords = Regex("""(还款成功|已还款|还款完成|已还清|偿还成功|还款入账|自动还款|主动还款|代扣还款)""")
    // 仅「提醒待还」信号(尚未发生还款):命中且无 [repaymentDoneWords] → 忽略(不把提醒落成还款草稿,§8)。
    private val repaymentReminderWords = Regex("""(待还款|还款日|请.{0,6}还款|尽快还款|即将到期|到期提醒|逾期|账单已出|本期应还)""")
    // 一般还款信号(无完成/提醒措辞时的兜底,如「花呗还款¥500」):在排除提醒后命中即判还款。
    private val repaymentWords = Regex("""(还款|偿还|还入|归还欠款)""")
    private val weChatPackages = setOf("com.tencent.mm")
    private val alipayPackages = setOf("com.eg.android.alipaygphone")
    // 京东(白条)/京东金融:白条还款。包名经联网核实(2026-06)。
    private val jdPackages = setOf("com.jingdong.app.mall", "com.jd.jrapp")
    // 美团:美团月付还款。
    private val meituanPackages = setOf("com.sankuai.meituan")
    private val smsPackages = setOf(
        "com.android.mms",
        "com.android.messaging",
        "com.google.android.apps.messaging",
        "com.samsung.android.messaging",
    )

    private enum class NotificationKind { REPAYMENT, EXPENSE }

    fun parse(snapshot: PaymentNotificationSnapshot): PaymentNotificationResult? {
        // 隐私 + 洁癖：**先按包名过滤**。非白名单（微信 / 支付宝 / 京东 / 美团 / 短信）的通知，连正文都不
        // 读——否则下面的 income/expense/还款正则会扫**每一条通知（任何 App）的正文内容**才决定丢弃。
        // 候选判定单列成 [isCandidatePackage]，可单测、把白名单文档化。
        if (!isCandidatePackage(snapshot.packageName)) return null
        val joined = snapshot.joinedText()
        if (joined.isBlank()) return null
        val amountCents = PaymentNotificationFields.parseAmountCents(joined) ?: return null
        return when (classifyKind(joined)) {
            NotificationKind.REPAYMENT -> buildRepayment(snapshot, joined, amountCents)
            NotificationKind.EXPENSE -> buildExpense(snapshot, joined, amountCents)
            null -> null
        }
    }

    /**
     * 包名是否在白名单内（=值不值得读这条通知的正文）。微信 / 支付宝 / 京东 / 京东金融 / 美团 / 短信类
     * 才算候选；其余（新闻、聊天、随便哪个 App）一律否，正文连看都不看。单列成 `internal` 以便单测钉死
     * 白名单边界。SMS 侧的进一步细分（需含 bankContext 才落 BankSms）仍在 [resolveSource] /
     * [resolveRepaymentSource]——本判定只做"要不要看正文"这一层粗过滤。
     */
    internal fun isCandidatePackage(packageName: String): Boolean {
        val pkg = packageName.lowercase()
        return pkg in weChatPackages || pkg in alipayPackages || pkg in jdPackages ||
            pkg in meituanPackages || isSmsPackage(pkg)
    }

    /**
     * 还款 vs 消费 vs 忽略的分类器（§还款分类器）。顺序即优先级，**修双计 bug 的关键**：
     * 收款 / 退款先排除 → 还款**已完成**信号（含「自动还款 / 扣款还款」）优先于消费 → 纯提醒（待还款 /
     * 还款日，尚未还）忽略 → 一般还款兜底 → 消费 → 其余忽略。这样含「还款」措辞的信用卡 / 花呗 / 白条
     * 还款绝不再落成支出草稿（哪怕正文同时含「扣款 / 成功」）。
     */
    private fun classifyKind(text: String): NotificationKind? = when {
        incomeOrRefundWords.containsMatchIn(text) -> null
        repaymentDoneWords.containsMatchIn(text) -> NotificationKind.REPAYMENT
        repaymentReminderWords.containsMatchIn(text) -> null
        repaymentWords.containsMatchIn(text) -> NotificationKind.REPAYMENT
        expenseWords.containsMatchIn(text) -> NotificationKind.EXPENSE
        else -> null
    }

    private fun buildRepayment(
        snapshot: PaymentNotificationSnapshot,
        joined: String,
        amountCents: Long,
    ): PaymentNotificationResult.Repayment? {
        val source = resolveRepaymentSource(snapshot.packageName, joined) ?: return null
        return PaymentNotificationResult.Repayment(
            RepaymentNotificationDraft(
                source = source,
                amountCents = amountCents,
                merchantLabel = PaymentNotificationFields.parseRepaymentLabel(joined),
                capturedAt = Instant.ofEpochMilli(snapshot.postTimeMillis).toString(),
            ),
        )
    }

    private fun buildExpense(
        snapshot: PaymentNotificationSnapshot,
        joined: String,
        amountCents: Long,
    ): PaymentNotificationResult.Expense? {
        val source = resolveSource(snapshot.packageName, joined) ?: return null
        return PaymentNotificationResult.Expense(
            NotificationDraft(
                source = source,
                amountCents = amountCents,
                merchant = PaymentNotificationFields.parseMerchant(snapshot, joined),
                category = null,
                expenseTime = Instant.ofEpochMilli(snapshot.postTimeMillis).toString(),
            ),
        )
    }

    private fun resolveSource(packageName: String, text: String): NotificationDraftSource? {
        val normalizedPackage = packageName.lowercase()
        return when {
            normalizedPackage in weChatPackages -> NotificationDraftSource.WeChat
            normalizedPackage in alipayPackages -> NotificationDraftSource.Alipay
            // 京东 / 美团只作为**还款**捕获渠道（杠杆③）：它们的消费通知不落支出草稿（NotificationDraftSource
            // 无 JD/Meituan 取值），故消费路径对这些包返回 null。
            isSmsPackage(normalizedPackage) -> {
                if (bankContext.containsMatchIn(text)) NotificationDraftSource.BankSms else null
            }
            else -> null
        }
    }

    private fun resolveRepaymentSource(packageName: String, text: String): RepaymentDraftSource? {
        val pkg = packageName.lowercase()
        return when {
            pkg in weChatPackages -> RepaymentDraftSource.WeChat
            pkg in alipayPackages -> RepaymentDraftSource.Alipay
            pkg in jdPackages -> RepaymentDraftSource.Jd
            pkg in meituanPackages -> RepaymentDraftSource.Meituan
            isSmsPackage(pkg) -> {
                if (bankContext.containsMatchIn(text)) RepaymentDraftSource.BankSms else null
            }
            else -> null
        }
    }

    private fun isSmsPackage(packageName: String): Boolean =
        packageName in smsPackages ||
            packageName.contains(".mms") ||
            packageName.contains(".sms") ||
            packageName.contains("messaging")
}

/** 通知正文字段抽取（金额 / 商家 / 还款标签）——纯文本解析,与分类逻辑拆开,各自函数数都在 detekt 门内。 */
private object PaymentNotificationFields {
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
    private val genericTitleWords = Regex("""(微信支付|支付宝|银行|通知|交易提醒|动账提醒|服务通知)""")
    // 还款标签:卡尾号 / 平台名(花呗 / 借呗 / 白条 / 美团月付),用于 ③b 模糊匹配与展示,可为空。
    private val cardTailPattern = Regex("""尾号\s*([0-9]{4})""")
    private val repaymentPlatformPattern = Regex("""(花呗|借呗|白条|美团月付|月付|信用卡)""")

    fun parseAmountCents(text: String): Long? {
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

    fun parseMerchant(snapshot: PaymentNotificationSnapshot, text: String): String? {
        for (pattern in merchantPatterns) {
            val candidate = pattern.find(text)?.groupValues?.getOrNull(1)
            cleanMerchant(candidate)?.let { return it }
        }
        return cleanMerchant(snapshot.title)
            ?.takeUnless { genericTitleWords.containsMatchIn(it) }
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

private fun PaymentNotificationSnapshot.joinedText(): String =
    listOf(title, text, bigText, subText)
        .mapNotNull { it?.trim()?.takeIf(String::isNotBlank) }
        .distinct()
        .joinToString(separator = "\n")
