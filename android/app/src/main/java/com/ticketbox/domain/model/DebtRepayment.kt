package com.ticketbox.domain.model

object DebtRepaymentStatuses {
    const val ACTIVE = "active"
    const val VOIDED = "voided"
}

/** A committed payment and its optional append-only correction; never a derived balance. */
data class DebtRepayment(
    val publicId: String,
    val amountCents: Long,
    val paidAt: String?,
    val createdAt: String,
    val status: String,
    val voidFact: DebtRepaymentVoid? = null,
    val originalCurrencyCode: String? = null,
    val originalAmountMinor: Long? = null,
    val exchangeRateToCny: String? = null,
    val exchangeRateDate: String? = null,
    val exchangeRateSource: String? = null,
    val accountingTime: ExpenseAccountingTime? = null,
) {
    val isActive: Boolean get() = status == DebtRepaymentStatuses.ACTIVE
}

data class DebtRepaymentVoid(val publicId: String, val reason: String, val createdAt: String)

/**
 * 单笔还款作废入口的展示资格（纯呈现规则，镜像服务端 guard_direct_fact_writable）：
 * 仅 external+manual 欠款、可写角色、整笔未作废（整笔 voided 是 terminal，服务端对后续
 * fact 一律 debt_already_voided）、该笔还款仍 active 时才出现；member/bill_split 的历史
 * 永远只读。已两清(cleared)不拦——作废一笔后服务端会重开父欠款。
 */
internal fun repaymentVoidActionAllowed(debt: Debt, canModify: Boolean, repayment: DebtRepayment): Boolean =
    debt.isDirectWritable && canModify && debt.status != DebtLinkStatuses.VOIDED && repayment.isActive
