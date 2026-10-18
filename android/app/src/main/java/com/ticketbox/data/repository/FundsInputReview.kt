package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.FinancialAccountDto

/** Refresh reviewed versions only; the raw money and original publication stay with their owners. */
internal suspend fun FundsQueries.reviewFundsInput(old: FundsInput, accounts: List<FinancialAccountDto>): FundsInput = when (old.mode) {
    "envelopes" -> reviewEnvelopes(old)
    "funding" -> reviewFunding(old, accounts)
    "void_activity" -> reviewActivity(old)
    else -> reviewAccount(old, accounts)
}

private suspend fun FundsQueries.reviewActivity(old: FundsInput): FundsInput {
    val read = detail(old.binding, old.accountId).getOrThrow()
    require(!read.fromCache) { "请联网核对所有相关账户，原输入保留。" }
    val source = requireNotNull(read.value.movements.find { it.eventPublicId == old.activityEventId }) { "原资金记录当前不可用。" }
    require(source.correctionParts.isNotEmpty()) { "原记录已撤销或相关账户当前不可用，请查看原记录。" }
    return old.copy(version = read.value.rowVersion, activityParts = source.correctionParts)
}

private suspend fun FundsQueries.reviewEnvelopes(old: FundsInput): FundsInput {
    val read = envelopes(old.binding, old.envelopeMonth).getOrThrow()
    require(!read.fromCache && read.value.homeCurrencyCode == old.currency) { "请联网核对信封的原币金额，原输入保留。" }
    return old.copy(version = read.value.rowVersion,
        envelopeAccountVersions = read.value.accounts.associate { it.publicId to it.rowVersion })
}

private suspend fun FundsQueries.reviewFunding(old: FundsInput, accounts: List<FinancialAccountDto>): FundsInput {
    val read = funding(old.binding, requireNotNull(old.expenseId)).getOrThrow()
    require(!read.fromCache && read.value.currencyCode == old.currency && read.value.canEdit) { "请联网核对消费及付款权限；原输入保留。" }
    val parts = requireNotNull(fundingInputAdapter.fromJson(old.fundingJson)).map { part ->
        val account = requireNotNull(accounts.firstOrNull { it.publicId == part.accountId }) { "原付款账户当前不可用。" }
        require(account.currencyCode == part.accountCurrency) { "原付款币种已变化，请保留原输入核对。" }
        part.copy(accountVersion = account.rowVersion)
    }
    return old.copy(version = read.value.expenseRowVersion, fundingJson = fundingInputAdapter.toJson(parts))
}

private fun reviewAccount(old: FundsInput, accounts: List<FinancialAccountDto>): FundsInput {
    val target = accounts.firstOrNull { it.publicId == old.accountId }
    val payer = accounts.firstOrNull { it.publicId == old.payerId }
    require(old.mode == "create" || target != null) { "账户当前不可用，原输入保留。" }
    require(target == null || target.currencyCode == old.currency) { "账户币种已变化，请核对原输入。" }
    require(payer == null || payer.currencyCode == old.payerCurrency) { "付款币种已变化，请核对原输入。" }
    return old.copy(version = target?.rowVersion ?: 0, calendarRevision = target?.calendarRevision ?: 0,
        payerVersion = payer?.rowVersion ?: 0)
}
