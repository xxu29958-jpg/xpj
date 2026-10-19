package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CreditPaymentVoidDto

/** Convert retained correction inputs without changing the original transaction. */
internal fun FundsInput.correctionCommand(): FundsCommand = when (mode) {
    "void_activity" -> voidActivityCommand()
    "void_repayment" -> voidPaymentCommand()
    else -> error("原纠错任务无法确认，输入仍保留。")
}

private fun FundsInput.voidActivityCommand(): FundsCommand {
    require(activityEventId.isNotBlank() && activityParts.isNotEmpty() && note.isNotBlank()) { "请核对原资金记录及所有相关账户，并填写撤销依据。" }
    return FundsCommand(revision = 5, binding = binding, accountId = accountId,
        voidActivity = com.ticketbox.data.remote.dto.AccountActivityVoidDto(version, activityEventId,
            activityParts.associate { it.accountPublicId to it.accountRowVersion }, date, note))
}

private fun FundsInput.voidPaymentCommand(): FundsCommand {
    require(repaymentId.isNotBlank() && note.isNotBlank()) { "请保留原还款并填写撤销依据。" }
    require(!legacyRepayment || reviewedDebtAmount.isNotBlank()) { "请核对接入旧还款后的当前欠款。" }
    val reviewed = reviewedDebtAmount.takeIf(String::isNotBlank)?.let { -fundsInputAmount(it, currency, signed = true) }
    return FundsCommand(revision = if (reviewed != null) 4 else 1, binding = binding, accountId = accountId,
        voidPayment = CreditPaymentVoidDto(version, repaymentId, date, note, reviewed))
}
