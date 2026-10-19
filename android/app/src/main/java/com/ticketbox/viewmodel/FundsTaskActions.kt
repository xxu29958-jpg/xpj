package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.InstallmentViewDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.FundsInputState
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.InstallmentInputWire
import com.ticketbox.data.repository.InstallmentPeriodInput
import com.ticketbox.data.repository.fundingInputs
import com.ticketbox.data.repository.withCreditApplicationSuggestion
import java.time.LocalDate
import java.util.UUID

fun FundsViewModel.start(mode: String) {
    val current = state.value
    val access = current.access?.takeIf { it.canModify } ?: return
    if (current.task.input != null) { mutable.value = mutable.value.copy(editing = true); return }
    payerQuoteJob?.cancel()
    suggestedPayerAmount = null
    if (mode == "funding") {
        val source = current.funding?.takeIf { it.canEdit } ?: return
        val value = FundsInput(access.binding, mode, UUID.randomUUID().toString(),
            expenseId = source.expenseId, version = source.expenseRowVersion, currency = source.currencyCode,
            fundingJson = fundingInputs(source))
        mutable.value = mutable.value.copy(task = FundsInputState(value), editing = true, error = null)
        save(value)
        return
    }
    val value = current.accountInput(access.binding, mode)
    mutable.value = mutable.value.copy(task = FundsInputState(value), editing = true, error = null)
    save(value)
}

fun FundsViewModel.choosePayer(account: FinancialAccountDto) = edit { it.copy(payerId = account.publicId, payerName = account.name,
    payerCurrency = account.currencyCode, payerVersion = account.rowVersion) }

fun FundsViewModel.voidPayment(id: String) {
    if (state.value.task.input != null) { resume(); return }
    start("void_repayment")
    edit { it.copy(repaymentId = id, legacyRepayment = state.value.detail?.priorRepayments?.items?.any { row -> row.publicId == id } == true) }
}

fun FundsViewModel.voidCreditApplication(id: String) {
    if (state.value.task.input != null) { resume(); return }
    start("void_credit")
    edit { it.copy(creditReviewId = id) }
}

fun FundsViewModel.voidActivity(row: com.ticketbox.data.remote.dto.FundMovementDto) {
    if (state.value.task.input != null) { resume(); return }
    if (row.correctionParts.isEmpty()) return
    start("void_activity")
    edit { it.copy(activityEventId = row.eventPublicId, activityLabel = row.note, activityParts = row.correctionParts) }
}

fun FundsViewModel.reviseAgreement(agreement: InstallmentViewDto) {
    if (state.value.task.input != null) { resume(); return }
    start("installments")
    val current = state.value
    val currency = com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(current.task.input?.currency) ?: return
    fun amount(value: Long) = java.math.BigDecimal.valueOf(value, currency.minorUnitDigits).toPlainString()
    edit { input -> input.copy(name = agreement.name, source = "", previousAgreement = agreement.publicId,
        drawIds = current.installments?.draws.orEmpty().filter { it.publicId in agreement.drawPublicIds && it.remainingMinor > 0 }.map { it.publicId },
        periodsJson = InstallmentInputWire.periods.toJson(agreement.periods.filter {
            it.principalMinor > it.paidPrincipalMinor || it.unincurredFeeMinor > 0
        }.map {
            InstallmentPeriodInput(it.dueOn, amount(it.principalMinor - it.paidPrincipalMinor), amount(it.unincurredFeeMinor)) })) }
}

private fun FundsUiState.accountInput(binding: LogicalSessionBinding, mode: String): FundsInput {
    var base = FundsInput(binding, mode, UUID.randomUUID().toString(), date = overview?.valuationDate ?: LocalDate.now().toString(),
        currency = overview?.homeCurrencyCode.orEmpty())
    if (mode in setOf("create", "repay")) repaymentCapture?.takeIf { it.isPending }?.let { capture ->
        val digits = com.ticketbox.domain.model.CurrencyCode.fromStorageKey(capture.originalCurrencyCode).minorUnitDigits
        val amount = java.math.BigDecimal.valueOf(capture.originalAmountMinor, digits).toPlainString()
        base = base.copy(kind = "credit", currency = capture.originalCurrencyCode,
            sourceRepaymentDraftId = capture.publicId, sourceCurrency = capture.originalCurrencyCode,
            sourceAmount = amount, sourceLabel = capture.merchantLabel.orEmpty(), note = capture.merchantLabel.orEmpty(),
            date = capture.accountingTime?.accountingDate ?: base.date)
    }
    if (mode == "create") return base
    val account = detail ?: return base
    val value = base.copy(accountId = account.publicId, version = account.rowVersion, calendarRevision = account.calendarRevision,
        name = account.name, kind = account.kind, currency = account.currencyCode, visibility = account.visibility,
        institution = account.institution.orEmpty(), tail = account.tail.orEmpty(), archived = account.archived, loanCurrency = account.currencyCode)
    return when (mode) {
        "edit" -> value.withCreditTerms(account.creditTerms)
        "apply_credit" -> value.withCreditApplicationSuggestion(account.creditApplications)
        else -> value
    }
}

private fun FundsInput.withCreditTerms(terms: com.ticketbox.data.remote.dto.CreditTermsDto?): FundsInput {
    if (terms == null) return this
    val digits = com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(currency)?.minorUnitDigits ?: return this
    fun amount(value: Long?) = value?.let { java.math.BigDecimal.valueOf(it, digits).toPlainString() }.orEmpty()
    return copy(creditLimit = amount(terms.creditLimitMinor), availableCredit = amount(terms.availableCreditMinor),
        creditObservedOn = terms.observedOn.orEmpty(), creditSource = terms.source.orEmpty(),
        statementDay = terms.statementDay?.toString().orEmpty(), paymentDueDay = terms.paymentDueDay?.toString().orEmpty())
}
