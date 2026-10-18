package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CreditApplicationCreateDto
import com.ticketbox.data.remote.dto.CreditApplicationVoidDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor
import com.ticketbox.data.remote.dto.CreditApplicationsDto

internal fun FundsInput.withCreditApplicationSuggestion(choices: CreditApplicationsDto?): FundsInput {
    val source = choices?.credits?.singleOrNull()
    val target = choices?.obligations?.singleOrNull()
    val amount = if (source != null && target != null) java.math.BigDecimal.valueOf(
        minOf(source.remainingMinor, target.remainingMinor), CurrencyCode.fromStorageKey(currency).minorUnitDigits).toPlainString() else ""
    return copy(creditSourceId = source?.publicId.orEmpty(), creditSourceLabel = source?.note.orEmpty(),
        creditDrawId = target?.publicId.orEmpty(), creditDrawLabel = target?.note.orEmpty(), activityAmount = amount)
}

internal fun FundsInput.creditApplicationCommand(): FundsCommand {
    require(note.isNotBlank()) { "请填写本次核对依据。" }
    if (mode == "void_credit") {
        require(creditReviewId.isNotBlank()) { "请从原抵扣记录办理撤销。" }
        return FundsCommand(revision = 3, binding = binding, accountId = accountId,
            voidCredit = CreditApplicationVoidDto(version, creditReviewId, note))
    }
    require(creditSourceId.isNotBlank() && creditDrawId.isNotBlank()) { "请选择余额来源和要抵扣的欠款。" }
    val amount = requireNotNull(parseExactMoneyMinor(activityAmount, CurrencyCode.fromStorageKey(currency))) { "请核对金额及币种的小数位。" }
    require(amount > 0) { "抵扣金额必须大于零。" }
    return FundsCommand(revision = 3, binding = binding, accountId = accountId,
        applyCredit = CreditApplicationCreateDto(version, creditSourceId, creditDrawId, amount, note))
}
