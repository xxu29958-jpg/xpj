package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseFunding
import com.ticketbox.domain.model.parseExactMoneyMinor

@JsonClass(generateAdapter = true)
data class ExpenseFundingInput(val componentId: String, val accountId: String, val accountVersion: Long,
    val accountName: String, val accountCurrency: String, val expenseCurrency: String,
    val expenseAmount: String = "", val accountAmount: String = "", val includedInOpening: Boolean = false)

internal val fundingInputAdapter = Moshi.Builder().build().adapter<List<ExpenseFundingInput>>(
    Types.newParameterizedType(List::class.java, ExpenseFundingInput::class.java))

internal fun readExpenseFunding(json: String, currency: CurrencyCode): List<ExpenseFunding> =
    requireNotNull(fundingInputAdapter.fromJson(json)).map { row ->
        require(row.expenseCurrency == currency.storageKey) { "原币种已改变，请重新核对资金组成。" }
        val native = requireNotNull(CurrencyCode.fromStorageKeyOrNull(row.accountCurrency)) { "原账户币种无法确认。" }
        ExpenseFunding(row.componentId, row.accountId, row.accountVersion,
            requireNotNull(parseExactMoneyMinor(row.expenseAmount, currency)) { "请填写每项原币金额。" },
            requireNotNull(parseExactMoneyMinor(row.accountAmount, native)) { "请填写每项账户实际金额。" }, row.includedInOpening,
            row.expenseCurrency, row.accountCurrency)
    }

internal fun fundingInputs(view: com.ticketbox.data.remote.dto.ExpenseFundingViewDto): String =
    fundingInputAdapter.toJson(view.parts.filter { it.accountPublicId != null }.map { row ->
        fun text(value: Long, code: String) = java.math.BigDecimal.valueOf(value,
            requireNotNull(CurrencyCode.fromStorageKeyOrNull(code)).minorUnitDigits).toPlainString()
        ExpenseFundingInput(row.componentId, requireNotNull(row.accountPublicId), requireNotNull(row.accountRowVersion),
            row.accountName, requireNotNull(row.currencyCode), view.currencyCode, text(row.expenseAmountMinor, view.currencyCode),
            text(requireNotNull(row.accountAmountMinor), row.currencyCode), row.includedInOpening)
    })

private val confirmationAdapter = Moshi.Builder().build().adapter(com.ticketbox.data.remote.dto.ExpenseStateTokenRequest::class.java)

internal fun OutboxRow.confirmationFunding() = if (type == com.ticketbox.data.local.PendingMutationType.ConfirmExpense)
    confirmationAdapter.fromJson(payloadJson)?.funding.orEmpty() else emptyList()

internal fun OutboxRow.canReviewFunding(): Boolean = runCatching {
    confirmationFunding().isNotEmpty() && status == com.ticketbox.data.local.PendingMutationStatus.Conflict
}.getOrDefault(false)

/** Currency travels with the original minor units; recovery must never reinterpret them in today's currency. */
internal fun reviewedFundingInputs(row: OutboxRow, accounts: List<com.ticketbox.data.remote.dto.FinancialAccountDto>): String =
    fundingInputAdapter.toJson(row.confirmationFunding().map { part ->
        val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(part.expenseCurrencyCode)) { "原消费币种无法核对，请保留原提交。" }
        val native = requireNotNull(CurrencyCode.fromStorageKeyOrNull(part.accountCurrencyCode)) { "原付款币种无法核对，请保留原提交。" }
        val account = accounts.firstOrNull { it.publicId == part.accountPublicId && it.currencyCode == native.storageKey && !it.archived }
        ExpenseFundingInput(part.componentId, part.accountPublicId, account?.rowVersion ?: part.accountRowVersion,
            account?.name ?: "原付款账户（现不可用）", native.storageKey, currency.storageKey,
            java.math.BigDecimal.valueOf(part.expenseAmountMinor, currency.minorUnitDigits).toPlainString(),
            java.math.BigDecimal.valueOf(part.accountAmountMinor, native.minorUnitDigits).toPlainString(), part.includedInOpening)
    })
