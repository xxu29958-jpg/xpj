package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.AccountPostingDto
import com.ticketbox.data.remote.dto.CreditPaymentDto
import com.ticketbox.data.remote.dto.ExpenseFundingCommandDto
import com.ticketbox.data.remote.dto.ExpenseFundingPartDto
import com.ticketbox.data.remote.dto.FinancialAccountCreateDto
import com.ticketbox.data.remote.dto.FinancialAccountEditDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor

internal fun FundsInput.command(): FundsCommand {
    if (mode !in setOf("funding", "envelopes", "apply_credit", "void_credit")) java.time.LocalDate.parse(date)
    require(tail.isEmpty() || tail.matches(Regex("[0-9]{1,4}"))) { "尾号只需填写最后 1 至 4 位数字。" }
    return when (mode) {
        "apply_credit", "void_credit" -> creditApplicationCommand()
        "incur_fee" -> {
            require(note.isNotBlank()) { "请填写已经发生的费用依据。" }
            FundsCommand(revision = 2, binding = binding, accountId = accountId,
                fee = com.ticketbox.data.remote.dto.CreditFeeCreateDto(version, calendarRevision,
                    fundsInputAmount(activityAmount, currency), date, note, feePeriodId.takeIf(String::isNotBlank)))
        }
        "envelopes" -> envelopeCommand()
        "void_repayment", "void_activity" -> correctionCommand()
        "installments" -> installmentsCommand()
        "funding" -> fundingCommand()
        "create" -> createCommand()
        "edit" -> editCommand()
        "repay" -> paymentCommand()
        "income", "loan", "transfer", "reconciliation" -> activityCommand()
        else -> error("原资金任务类型无法确认，输入仍保留。")
    }
}

private fun FundsInput.envelopeCommand(): FundsCommand {
    java.time.YearMonth.parse(envelopeMonth)
    return FundsCommand(binding = binding, accountId = "", envelopeMonth = envelopeMonth,
        envelopes = com.ticketbox.data.remote.dto.EnvelopeSaveDto(version, currency, envelopeAccounts,
            envelopeAccountVersions, envelopeAmounts.mapValues { fundsInputAmount(it.value, currency) }, note))
}

internal fun fundsInputAmount(text: String, code: String, signed: Boolean = false): Long = requireNotNull(parseExactMoneyMinor(text,
        requireNotNull(CurrencyCode.fromStorageKeyOrNull(code)) { "请先选择原币种。" }, allowNegative = signed)) { "请核对金额及币种的小数位。" }

private fun FundsInput.creditTerms(): com.ticketbox.domain.model.CreditTerms? {
        if (kind != "credit") return null
        fun day(value: String): Int? = value.takeIf(String::isNotBlank)?.let {
            requireNotNull(it.toIntOrNull()?.takeIf { day -> day in 1..31 }) { "账单日和还款日请填写 1 至 31。" }
        }
        if (creditLimit.isNotBlank() || availableCredit.isNotBlank()) {
            java.time.LocalDate.parse(creditObservedOn)
            require(creditSource.isNotBlank()) { "请填写额度查询来源。" }
        }
        return com.ticketbox.domain.model.CreditTerms(creditLimit.takeIf(String::isNotBlank)?.let { fundsInputAmount(it, currency) },
            availableCredit.takeIf(String::isNotBlank)?.let { fundsInputAmount(it, currency) }, creditObservedOn.ifBlank { null },
            day(statementDay), day(paymentDueDay), creditSource.ifBlank { null })
    }

private fun FundsInput.installmentsCommand(): FundsCommand = FundsCommand(binding = binding, accountId = accountId, installments = installmentCommand())

private fun FundsInput.fundingCommand(): FundsCommand {
    require(expenseId != null && note.isNotBlank()) { "请保留原消费并填写核对依据。" }
            val parts = readExpenseFunding(fundingJson, requireNotNull(CurrencyCode.fromStorageKeyOrNull(currency)))
            require(parts.isNotEmpty()) { "请选择实际付款来源。" }
            return FundsCommand(binding = binding, accountId = "", expenseId = expenseId,
                funding = ExpenseFundingCommandDto(version, parts.map { ExpenseFundingPartDto(it.componentId,
                    it.accountPublicId, it.accountRowVersion, it.expenseAmountMinor, it.accountAmountMinor,
                    it.includedInOpening, it.expenseCurrencyCode, it.accountCurrencyCode) }, note))
}

private fun FundsInput.createCommand(): FundsCommand {
    require(name.isNotBlank() && source.isNotBlank()) { "请填写账户名称和期初依据。" }
            val adoption = existingDebtId.takeIf(String::isNotBlank)?.let {
                require(kind == "credit" && opening.isNotBlank() && existingDebtVersion > 0) { "接入旧欠款时，请选择信用账户并核对实际币种和期初欠款。" }
                com.ticketbox.data.remote.dto.DebtAdoptionDto(it, existingDebtVersion)
            }
            return FundsCommand(binding = binding, accountId = "", create = FinancialAccountCreateDto(name.trim(), kind, currency,
                visibility, institution.trim().ifBlank { null }, tail.trim().ifBlank { null },
                opening.takeIf { it.isNotBlank() }?.let { fundsInputAmount(it, currency, signed = true) }, date, source, creditTerms(), adoption))
}

private fun FundsInput.editCommand(): FundsCommand = FundsCommand(binding = binding, accountId = accountId, edit = FinancialAccountEditDto(version,
            name.trim(), institution.trim().ifBlank { null }, tail.trim().ifBlank { null }, archived, creditTerms(), visibilityEdit))

private fun FundsInput.paymentCommand(): FundsCommand {
    require(payerId.isNotBlank() && payerVersion > 0 && note.isNotBlank()) { "请选择实际扣款账户并填写说明。" }
            val (periods, draws) = paymentAllocation()
            return FundsCommand(revision = if (feePayments.isEmpty()) 1 else 2, binding = binding, accountId = accountId, payment = CreditPaymentDto(version, calendarRevision,
                payerId, payerVersion, fundsInputAmount(principal, currency), fundsInputAmount(paid, payerCurrency), date, note,
                newFee.takeIf { it.isNotBlank() }?.let { fundsInputAmount(it, payerCurrency) } ?: 0L, feeNote.ifBlank { null },
                periods, draws, overpayment.takeIf(String::isNotBlank)?.let { fundsInputAmount(it, currency) } ?: 0L,
                sourceRepaymentDraftId.takeIf(String::isNotBlank), sourceAmountBasis,
                sourceReviewReason.takeIf(String::isNotBlank),
                feePayments.filterValues(String::isNotBlank).map { (id, value) ->
                    com.ticketbox.data.remote.dto.CreditFeePaymentPartDto(id.toLong(), fundsInputAmount(value, currency))
                }.filter { it.amountMinor > 0 }, payerFeeAmount.takeIf(String::isNotBlank)?.let { fundsInputAmount(it, payerCurrency) } ?: 0L))
}

private fun FundsInput.activityCommand(): FundsCommand {
    require(note.isNotBlank()) { "请填写实际来源或核对依据。" }
            return FundsCommand(binding = binding, accountId = accountId, activity = AccountPostingDto(version, mode,
                fundsInputAmount(activityAmount, currency, signed = mode == "reconciliation") * if (mode == "reconciliation" && kind == "credit") -1 else 1,
                date, note, calendarRevision, payerId.takeIf { mode == "transfer" }, payerVersion.takeIf { mode == "transfer" },
                if (mode == "transfer") fundsInputAmount(otherAmount, payerCurrency) else null, applyAdjustment,
                loanName.takeIf { mode == "loan" }, loanCurrency.takeIf { mode == "loan" },
                if (mode == "loan") fundsInputAmount(loanPrincipal, loanCurrency) else null))
}
