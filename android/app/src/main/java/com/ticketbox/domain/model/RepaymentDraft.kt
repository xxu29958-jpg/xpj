package com.ticketbox.domain.model

/**
 * ADR-0049 §杠杆③ NLS 还款捕获（slice 3a）领域模型。
 *
 * NLS 把一条「信用卡 / 花呗 / 借呗 / 白条 / 美团月付」**还款**通知分类后，落成一条 PENDING 的
 * [RepaymentDraft]（永不自动记账，§8）。用户在复核箱里选一笔 open 的 external/manual 欠款 confirm
 * （记一笔 `Repayment`）或 dismiss。捕获是本位币（CNY 通知不带 FX）。
 *
 * 三类值对象：
 * - [RepaymentDraftSource]：NLS 分类出的捕获渠道（与后端 `REPAYMENT_DRAFT_SOURCE_LABELS` 的键一一对应）。
 * - [RepaymentNotificationDraft]：NLS 抠出、即将 POST 的捕获载荷（提交前的本地形态）。
 * - [RepaymentDraft]：复核箱列表项（从服务端读回，含 status / committed 关联）。
 */
enum class RepaymentDraftSource(val apiValue: String) {
    // 支付宝：花呗 / 借呗还款。
    Alipay("alipay"),

    // 京东 / 京东金融：白条还款。
    Jd("jd"),

    // 美团：美团月付还款。
    Meituan("meituan"),

    // 微信：信用卡还款。
    WeChat("wechat"),

    // 银行还款短信。
    BankSms("bank_sms"),

    // 银行 App 还款通知（当前白名单未含具体银行 App 包，预留）。
    BankApp("bank_app"),

    Other("other"),
}

/**
 * NLS 抠出、即将 POST 到 `/api/repayment-drafts` 的还款捕获载荷。本位币（CNY 通知无 FX），故只有
 * [amountCents]（本位币分）；[capturedAt] 是通知投递时刻（confirm 时透传成 `Repayment.paid_at`，
 * 让晚几天复核也不把还款时间回填到复核时刻）。[merchantLabel] 是尽力抠出的卡 / 平台标签（尾号 /
 * 花呗 / 白条…），用于 ③b 模糊匹配与展示，可为空（③a 用户手动选债，匹配不到也无妨）。
 */
data class RepaymentNotificationDraft(
    val source: RepaymentDraftSource,
    val amountCents: Long,
    val merchantLabel: String?,
    val capturedAt: String?,
)

/** [RepaymentDraft.status] 的服务端取值，UI 据此渲染与分支（镜像后端 RepaymentDraft.status）。 */
object RepaymentDraftStatuses {
    const val PENDING = "pending"
    const val CONFIRMED = "confirmed"
    const val DISMISSED = "dismissed"
}

/**
 * 复核箱列表项：一条 NLS 捕获的还款草稿。`amount`/`source`/`status` 全由服务端权威，客户端只渲染。
 * [source] 是原始 api 值（alipay / jd / …），展示层经 `repaymentDraftSourceLabelRes` 映射到中文标签。
 */
data class RepaymentDraft(
    val publicId: String,
    val source: String,
    val amountCents: Long,
    val homeCurrencyCode: String,
    val merchantLabel: String?,
    val capturedAt: String,
    val status: String,
    val committedDebtPublicId: String?,
    val committedRepaymentPublicId: String?,
    val createdAt: String,
    val resolvedAt: String?,
) {
    val isPending: Boolean get() = status == RepaymentDraftStatuses.PENDING
}
