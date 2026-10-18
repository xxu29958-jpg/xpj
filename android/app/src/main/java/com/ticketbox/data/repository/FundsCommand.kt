package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.remote.ApiService
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
import com.ticketbox.data.remote.dto.InstallmentCommandDto
import com.ticketbox.data.remote.dto.InstallmentsDto
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
    val existingDebtId: String = "", val existingDebtVersion: Long = 0, val existingDebtLabel: String = "",
    val sourceRepaymentDraftId: String = "", val sourceAmountBasis: String = "payer_total",
    val sourceReviewReason: String = "", val sourceCurrency: String = "", val sourceAmount: String = "",
    val sourceLabel: String = "", val envelopeMonth: String = "",
    val envelopeAccounts: List<String> = emptyList(), val envelopeAccountVersions: Map<String, Long> = emptyMap(),
    val envelopeAmounts: Map<String, String> = emptyMap(), val visibilityEdit: String? = null,
    val feePeriodId: String = "", val feePeriodLabel: String = "", val feePayments: Map<String, String> = emptyMap(),
    val payerFeeAmount: String = "", val creditSourceId: String = "", val creditDrawId: String = "",
    val creditReviewId: String = "", val creditSourceLabel: String = "", val creditDrawLabel: String = "",
    val legacyRepayment: Boolean = false, val reviewedDebtAmount: String = "",
    val activityEventId: String = "", val activityLabel: String = "",
    val activityParts: List<com.ticketbox.data.remote.dto.ActivityCorrectionPartDto> = emptyList())

@JsonClass(generateAdapter = true)
data class FundsCommand(val revision: Int = 1, val binding: LogicalSessionBinding, val accountId: String,
    val create: FinancialAccountCreateDto? = null, val edit: FinancialAccountEditDto? = null,
    val payment: CreditPaymentDto? = null, val activity: AccountPostingDto? = null,
    val expenseId: Long? = null, val funding: ExpenseFundingCommandDto? = null, val installments: InstallmentCommandDto? = null,
    val voidPayment: CreditPaymentVoidDto? = null, val envelopes: com.ticketbox.data.remote.dto.EnvelopeSaveDto? = null,
    val envelopeMonth: String = "", val fee: com.ticketbox.data.remote.dto.CreditFeeCreateDto? = null,
    val applyCredit: com.ticketbox.data.remote.dto.CreditApplicationCreateDto? = null,
    val voidCredit: com.ticketbox.data.remote.dto.CreditApplicationVoidDto? = null,
    val voidActivity: com.ticketbox.data.remote.dto.AccountActivityVoidDto? = null) {
    val version: Long get() = voidActivity?.expectedRowVersion ?: applyCredit?.expectedRowVersion ?: voidCredit?.expectedRowVersion ?: fee?.expectedRowVersion ?: edit?.expectedRowVersion ?: payment?.expectedRowVersion ?: activity?.expectedRowVersion ?: funding?.expectedRowVersion ?: installments?.expectedRowVersion ?: voidPayment?.expectedRowVersion ?: envelopes?.expectedRowVersion ?: 0L
    fun target(key: String) = when {
        envelopes != null -> "funds:envelopes:$envelopeMonth"
        funding != null -> "funds:expense:$expenseId"
        else -> "funds:${accountId.ifBlank { key }}"
    }
}

internal object FundsWire {
    private val moshi = Moshi.Builder().build()
    val input = moshi.adapter(FundsInput::class.java)
    val command = moshi.adapter(FundsCommand::class.java)
    val account = moshi.adapter(FinancialAccountDto::class.java)
    val envelopeHistory = moshi.adapter<List<com.ticketbox.data.remote.dto.EnvelopeRevisionDto>>(
        Types.newParameterizedType(List::class.java, com.ticketbox.data.remote.dto.EnvelopeRevisionDto::class.java))
    val overview = moshi.adapter(FundsOverviewDto::class.java)
    val funding = moshi.adapter(ExpenseFundingViewDto::class.java)
    val installments = moshi.adapter(InstallmentsDto::class.java)
    val envelopes = moshi.adapter(com.ticketbox.data.remote.dto.EnvelopesDto::class.java)
    val listing = moshi.adapter<List<FinancialAccountDto>>(Types.newParameterizedType(List::class.java, FinancialAccountDto::class.java))
    val choices = moshi.adapter<List<com.ticketbox.data.remote.dto.AccountChoiceDto>>(
        Types.newParameterizedType(List::class.java, com.ticketbox.data.remote.dto.AccountChoiceDto::class.java))
    val existingDebts = moshi.adapter<List<com.ticketbox.data.remote.dto.ExistingDebtChoiceDto>>(
        Types.newParameterizedType(List::class.java, com.ticketbox.data.remote.dto.ExistingDebtChoiceDto::class.java))
}


internal const val FUNDS_REFUSED = "资金请求未接受："

internal class FundsCommandDispatcher(private val guard: LedgerRequestGuard) : OutboxMutationDispatcher {
    override val type = PendingMutationType.FinancialAccountCommand
    private val errors = NetworkErrorHandler({ null }, "Funds")
    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        val original = original(row) ?: return DispatchResult.Failure("原资金提交无法读取，输入已保留。", definitelyRejected = true)
        return try {
            val bound = guard.bindExact(original.binding)
            val api = bound.serviceFor(requireNotNull(row.bindingOrNull()))
            val key = requireNotNull(row.idempotencyKey)
            if (original.envelopes != null) {
                val result = api.saveEnvelopes(original.envelopeMonth, original.envelopes, key)
                require(result.ledgerId == original.binding.ledgerId && result.month == original.envelopeMonth &&
                    result.homeCurrencyCode == original.envelopes.homeCurrencyCode && result.rowVersion > original.version)
                bound.requireStillActive()
                return DispatchResult.Success(receiptJson = FundsWire.envelopes.toJson(result))
            }
            if (original.funding != null) {
                val result = api.saveExpenseFunding(requireNotNull(original.expenseId), original.funding, key)
                require(result.expenseId == original.expenseId && result.expenseRowVersion > original.version)
                bound.requireStillActive()
                return DispatchResult.Success(receiptJson = FundsWire.funding.toJson(result))
            }
            val result = accountResult(original, api, key)
            bound.requireStillActive()
            DispatchResult.Success(receiptJson = FundsWire.account.toJson(result))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: HttpException) {
            httpFailure(error)
        } catch (_: IOException) {
            DispatchResult.RetryableFailure("连接中断，将核实原资金提交。")
        } catch (_: RepositoryException) {
            DispatchResult.RetryableFailure("原资金任务的身份已变化，请切回原身份核对。")
        } catch (error: Exception) {
            logNetworkWarning("Funds response unverified", error)
            DispatchResult.Failure("尚未确认资金回执，保留原提交核实。")
        }
    }

    private fun original(row: OutboxRow) = runCatching {
            require(row.type == type && !row.idempotencyKey.isNullOrBlank())
            val value = requireNotNull(FundsWire.command.fromJson(row.payloadJson))
            require(value.revision in 1..5 && listOf(value.create, value.edit, value.payment, value.activity, value.funding, value.installments, value.voidPayment, value.envelopes, value.fee, value.applyCredit, value.voidCredit, value.voidActivity).count { it != null } == 1)
            require(row.expectedRowVersion == value.version && row.targetId == value.target(requireNotNull(row.idempotencyKey)))
            value
        }.getOrNull()

    private suspend fun accountResult(original: FundsCommand, api: ApiService, key: String): FinancialAccountDto {
        val result = when {
                original.voidActivity != null -> api.voidFundsActivity(original.accountId, original.voidActivity, key)
                original.applyCredit != null -> api.applyRetainedCredit(original.accountId, original.applyCredit, key)
                original.voidCredit != null -> api.voidCreditApplication(original.accountId, original.voidCredit, key)
                original.fee != null -> api.incurCreditFee(original.accountId, original.fee, key)
                original.create != null -> api.createFundsAccount(original.create, key)
                original.edit != null -> api.editFundsAccount(original.accountId, original.edit, key)
                original.activity != null -> api.postFundsActivity(original.accountId, original.activity, key)
                original.installments != null -> api.saveInstallments(original.accountId, original.installments, key)
                original.voidPayment != null -> api.voidCreditPayment(original.accountId, original.voidPayment, key)
                else -> api.payCreditAccount(original.accountId, requireNotNull(original.payment), key)
            }
            require(result.publicId.isNotBlank() && result.rowVersion > 0 &&
                (original.accountId.isBlank() || result.publicId == original.accountId))
        return result
    }

    private fun httpFailure(error: HttpException): DispatchResult {
            val parsed = errors.parseHttpError(error)
            return when {
                error.code() in setOf(408, 429) || error.code() >= 500 || parsed.errorCode == "idempotency_key_in_progress" ->
                    DispatchResult.RetryableFailure("连接中断，将核实原资金提交。")
                parsed.errorCode == "state_conflict" -> DispatchResult.Conflict(parsed.message)
                else -> {
                    val refused = parsed.errorCode in setOf("invalid_request", "amount_invalid", "funding_amount_mismatch",
                        "envelope_cash_unknown", "envelope_cash_insufficient", "balance_review_required", "fund_activity_already_voided", "fund_activity_not_found",
                        "fund_account_archived", "fund_account_in_envelopes", "credit_opening_unknown", "exchange_rate_pending", "calendar_revision_conflict",
                        "funding_review_required", "funding_opening_mismatch", "funding_opening_review_required",
                        "expense_reversal_active", "funds_date_outside_coverage", "funding_requires_confirmation", "repayment_already_voided",
                        "credit_adoption_unavailable", "credit_adoption_date_conflict", "credit_account_required",
                        "installment_source_required", "installment_source_in_use", "installment_amount_mismatch", "installment_allocation_required", "installment_review_required")
                    DispatchResult.Failure((if (refused) FUNDS_REFUSED else "") + parsed.message,
                        definitelyRejected = refused, credentialRejected = error.code() == 401)
                }
            }
    }
}
