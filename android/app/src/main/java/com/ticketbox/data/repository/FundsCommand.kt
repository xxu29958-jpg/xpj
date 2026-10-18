package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.CreditPaymentDto
import com.ticketbox.data.remote.dto.CreditPaymentVoidDto
import com.ticketbox.data.remote.dto.FinancialAccountCreateDto
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FinancialAccountEditDto
import com.ticketbox.data.remote.dto.AccountPostingDto
import com.ticketbox.data.remote.dto.FundsOverviewDto
import com.ticketbox.data.remote.dto.ExpenseFundingViewDto
import com.ticketbox.data.remote.dto.ExpenseFundingCommandDto
import com.ticketbox.data.remote.dto.ExpenseFundingPartDto
import com.ticketbox.data.remote.dto.InstallmentCommandDto
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor
import java.io.IOException
import kotlinx.coroutines.CancellationException
import retrofit2.HttpException

@JsonClass(generateAdapter = true)
data class FundsInput(val binding: LogicalSessionBinding, val mode: String, val key: String,
    val accountId: String = "", val version: Long = 0, val calendarRevision: Long = 0,
    val name: String = "", val kind: String = "bank", val currency: String = "", val visibility: String = "private",
    val institution: String = "", val tail: String = "", val opening: String = "", val date: String = "",
    val source: String = "本人核对", val archived: Boolean = false,
    val payerId: String = "", val payerName: String = "", val payerCurrency: String = "", val payerVersion: Long = 0,
    val principal: String = "", val paid: String = "", val note: String = "",
    val newFee: String = "", val feeNote: String = "", val activityAmount: String = "", val otherAmount: String = "",
    val applyAdjustment: Boolean = false, val loanName: String = "", val loanCurrency: String = "", val loanPrincipal: String = "",
    val expenseId: Long? = null, val fundingJson: String = "[]", val previousAgreement: String = "",
    val drawIds: List<String> = emptyList(), val periodsJson: String = "[]", val allocationJson: String = "[]", val overpayment: String = "",
    val repaymentId: String = "", val creditLimit: String = "", val availableCredit: String = "",
    val creditObservedOn: String = "", val creditSource: String = "", val statementDay: String = "", val paymentDueDay: String = "",
    val existingDebtId: String = "", val existingDebtVersion: Long = 0, val existingDebtLabel: String = "")

@JsonClass(generateAdapter = true)
data class FundsCommand(val revision: Int = 1, val binding: LogicalSessionBinding, val accountId: String,
    val create: FinancialAccountCreateDto? = null, val edit: FinancialAccountEditDto? = null,
    val payment: CreditPaymentDto? = null, val activity: AccountPostingDto? = null,
    val expenseId: Long? = null, val funding: ExpenseFundingCommandDto? = null, val installments: InstallmentCommandDto? = null,
    val voidPayment: CreditPaymentVoidDto? = null) {
    val version: Long get() = edit?.expectedRowVersion ?: payment?.expectedRowVersion ?: activity?.expectedRowVersion ?: funding?.expectedRowVersion ?: installments?.expectedRowVersion ?: voidPayment?.expectedRowVersion ?: 0L
    fun target(key: String) = if (funding != null) "funds:expense:$expenseId" else "funds:${accountId.ifBlank { key }}"
}

internal object FundsWire {
    private val moshi = Moshi.Builder().build()
    val input = moshi.adapter(FundsInput::class.java)
    val command = moshi.adapter(FundsCommand::class.java)
    val account = moshi.adapter(FinancialAccountDto::class.java)
    val overview = moshi.adapter(FundsOverviewDto::class.java)
    val funding = moshi.adapter(ExpenseFundingViewDto::class.java)
    val installments = moshi.adapter(InstallmentsDto::class.java)
    val listing = moshi.adapter<List<FinancialAccountDto>>(Types.newParameterizedType(List::class.java, FinancialAccountDto::class.java))
    val choices = moshi.adapter<List<com.ticketbox.data.remote.dto.AccountChoiceDto>>(
        Types.newParameterizedType(List::class.java, com.ticketbox.data.remote.dto.AccountChoiceDto::class.java))
    val existingDebts = moshi.adapter<List<com.ticketbox.data.remote.dto.ExistingDebtChoiceDto>>(
        Types.newParameterizedType(List::class.java, com.ticketbox.data.remote.dto.ExistingDebtChoiceDto::class.java))
}

internal fun FundsInput.command(): FundsCommand {
    fun amount(text: String, code: String, signed: Boolean = false): Long = requireNotNull(parseExactMoneyMinor(text,
        requireNotNull(CurrencyCode.fromStorageKeyOrNull(code)) { "请先选择原币种。" }, allowNegative = signed)) { "请核对金额及币种的小数位。" }
    if (mode != "funding") java.time.LocalDate.parse(date)
    fun creditTerms(): com.ticketbox.data.remote.dto.CreditTermsDto? {
        if (kind != "credit") return null
        fun day(value: String): Int? = value.takeIf(String::isNotBlank)?.let {
            requireNotNull(it.toIntOrNull()?.takeIf { day -> day in 1..31 }) { "账单日和还款日请填写 1 至 31。" }
        }
        if (creditLimit.isNotBlank() || availableCredit.isNotBlank()) {
            java.time.LocalDate.parse(creditObservedOn)
            require(creditSource.isNotBlank()) { "请填写额度查询来源。" }
        }
        return com.ticketbox.data.remote.dto.CreditTermsDto(creditLimit.takeIf(String::isNotBlank)?.let { amount(it, currency) },
            availableCredit.takeIf(String::isNotBlank)?.let { amount(it, currency) }, creditObservedOn.ifBlank { null },
            day(statementDay), day(paymentDueDay), creditSource.ifBlank { null })
    }
    val result = when (mode) {
        "void_repayment" -> {
            require(repaymentId.isNotBlank() && note.isNotBlank()) { "请保留原还款并填写撤销依据。" }
            FundsCommand(binding = binding, accountId = accountId,
                voidPayment = CreditPaymentVoidDto(version, repaymentId, date, note))
        }
        "installments" -> FundsCommand(binding = binding, accountId = accountId, installments = installmentCommand())
        "funding" -> {
            require(expenseId != null && note.isNotBlank()) { "请保留原消费并填写核对依据。" }
            val parts = readExpenseFunding(fundingJson, requireNotNull(CurrencyCode.fromStorageKeyOrNull(currency)))
            require(parts.isNotEmpty()) { "请选择实际付款来源。" }
            FundsCommand(binding = binding, accountId = "", expenseId = expenseId,
                funding = ExpenseFundingCommandDto(version, parts.map { ExpenseFundingPartDto(it.componentId,
                    it.accountPublicId, it.accountRowVersion, it.expenseAmountMinor, it.accountAmountMinor,
                    it.includedInOpening, it.expenseCurrencyCode, it.accountCurrencyCode) }, note))
        }
        "create" -> {
            require(name.isNotBlank() && source.isNotBlank()) { "请填写账户名称和期初依据。" }
            val adoption = existingDebtId.takeIf(String::isNotBlank)?.let {
                require(kind == "credit" && opening.isNotBlank() && existingDebtVersion > 0) { "接入旧欠款时，请选择信用账户并核对实际币种和期初欠款。" }
                com.ticketbox.data.remote.dto.DebtAdoptionDto(it, existingDebtVersion)
            }
            FundsCommand(binding = binding, accountId = "", create = FinancialAccountCreateDto(name.trim(), kind, currency,
                visibility, institution.trim().ifBlank { null }, tail.trim().ifBlank { null },
                opening.takeIf { it.isNotBlank() }?.let { amount(it, currency, signed = true) }, date, source, creditTerms(), adoption))
        }
        "edit" -> FundsCommand(binding = binding, accountId = accountId, edit = FinancialAccountEditDto(version,
            name.trim(), institution.trim().ifBlank { null }, tail.trim().ifBlank { null }, archived, creditTerms()))
        "repay" -> {
            require(payerId.isNotBlank() && payerVersion > 0 && note.isNotBlank()) { "请选择实际扣款账户并填写说明。" }
            val (periods, draws) = paymentAllocation()
            FundsCommand(binding = binding, accountId = accountId, payment = CreditPaymentDto(version, calendarRevision,
                payerId, payerVersion, amount(principal, currency), amount(paid, payerCurrency), date, note,
                newFee.takeIf { it.isNotBlank() }?.let { amount(it, payerCurrency) } ?: 0L, feeNote.ifBlank { null },
                periods, draws, overpayment.takeIf(String::isNotBlank)?.let { amount(it, currency) } ?: 0L))
        }
        "income", "loan", "transfer", "reconciliation" -> {
            require(note.isNotBlank()) { "请填写实际来源或核对依据。" }
            FundsCommand(binding = binding, accountId = accountId, activity = AccountPostingDto(version, mode,
                amount(activityAmount, currency, signed = mode == "reconciliation") * if (mode == "reconciliation" && kind == "credit") -1 else 1,
                date, note, calendarRevision, payerId.takeIf { mode == "transfer" }, payerVersion.takeIf { mode == "transfer" },
                if (mode == "transfer") amount(otherAmount, payerCurrency) else null, applyAdjustment,
                loanName.takeIf { mode == "loan" }, loanCurrency.takeIf { mode == "loan" },
                if (mode == "loan") amount(loanPrincipal, loanCurrency) else null))
        }
        else -> error("原资金任务类型无法确认，输入仍保留。")
    }
    require(tail.isEmpty() || tail.matches(Regex("[0-9]{1,4}"))) { "尾号只需填写最后 1 至 4 位数字。" }
    return result
}

internal const val FUNDS_REFUSED = "资金请求未接受："

internal class FundsCommandDispatcher(private val guard: LedgerRequestGuard) : OutboxMutationDispatcher {
    override val type = PendingMutationType.FinancialAccountCommand
    private val errors = NetworkErrorHandler({ null }, "Funds")
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = runCatching {
            require(row.type == type && !row.idempotencyKey.isNullOrBlank())
            val value = requireNotNull(FundsWire.command.fromJson(row.payloadJson))
            require(value.revision == 1 && listOf(value.create, value.edit, value.payment, value.activity, value.funding, value.installments, value.voidPayment).count { it != null } == 1)
            require(row.expectedRowVersion == value.version && row.targetId == value.target(requireNotNull(row.idempotencyKey)))
            value
        }.getOrNull() ?: return DispatchResult.Failure("原资金提交无法读取，输入已保留。", definitelyRejected = true)
        return try {
            val bound = guard.bindExact(original.binding)
            val api = bound.serviceFor(requireNotNull(row.bindingOrNull()))
            val key = requireNotNull(row.idempotencyKey)
            if (original.funding != null) {
                val result = api.saveExpenseFunding(requireNotNull(original.expenseId), original.funding, key)
                require(result.expenseId == original.expenseId && result.expenseRowVersion > original.version)
                bound.requireStillActive()
                return DispatchResult.Success(receiptJson = FundsWire.funding.toJson(result))
            }
            val result = when {
                original.create != null -> api.createFundsAccount(original.create, key)
                original.edit != null -> api.editFundsAccount(original.accountId, original.edit, key)
                original.activity != null -> api.postFundsActivity(original.accountId, original.activity, key)
                original.installments != null -> api.saveInstallments(original.accountId, original.installments, key)
                original.voidPayment != null -> api.voidCreditPayment(original.accountId, original.voidPayment, key)
                else -> api.payCreditAccount(original.accountId, requireNotNull(original.payment), key)
            }
            require(result.publicId.isNotBlank() && result.rowVersion > 0 &&
                (original.accountId.isBlank() || result.publicId == original.accountId))
            bound.requireStillActive()
            DispatchResult.Success(receiptJson = FundsWire.account.toJson(result))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: HttpException) {
            val parsed = errors.parseHttpError(error)
            when {
                error.code() in setOf(408, 429) || error.code() >= 500 || parsed.errorCode == "idempotency_key_in_progress" ->
                    DispatchResult.RetryableFailure("连接中断，将核实原资金提交。")
                parsed.errorCode == "state_conflict" -> DispatchResult.Conflict(parsed.message)
                else -> {
                    val refused = parsed.errorCode in setOf("invalid_request", "amount_invalid", "funding_amount_mismatch",
                        "fund_account_archived", "credit_opening_unknown", "exchange_rate_pending", "calendar_revision_conflict",
                        "funding_review_required", "funding_opening_mismatch", "funding_opening_review_required",
                        "expense_reversal_active", "funds_date_outside_coverage", "funding_requires_confirmation", "repayment_already_voided",
                        "credit_adoption_unavailable", "credit_adoption_date_conflict", "credit_account_required",
                        "installment_source_in_use", "installment_amount_mismatch", "installment_allocation_required", "installment_review_required")
                    DispatchResult.Failure((if (refused) FUNDS_REFUSED else "") + parsed.message,
                        definitelyRejected = refused, credentialRejected = error.code() == 401)
                }
            }
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("连接中断，将核实原资金提交。")
        } catch (_: RepositoryException) {
            DispatchResult.RetryableFailure("原资金任务的身份已变化，请切回原身份核对。")
        } catch (error: Exception) {
            logNetworkWarning("Funds response unverified", error)
            DispatchResult.RetryableFailure("尚未确认资金回执，保留原提交核实。")
        }
    }
}
