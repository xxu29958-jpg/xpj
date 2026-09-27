package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.MonthlyArrangementSaveRequest
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ledgerRoleCanModify

interface BudgetAdviceInputsActions {
    suspend fun adviceInputs(expectedBinding: LogicalSessionBinding, month: String,
        homeCurrencyCode: String? = null): Result<BudgetAdviceInputsDto>
    suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String,
        request: MonthlyArrangementSaveRequest, reportingHomeCurrencyCode: String? = null): Result<BudgetAdviceInputsDto>
    suspend fun requestTrialAdvice(binding: LogicalSessionBinding, month: String,
        request: MonthlyArrangementSaveRequest, reportingHomeCurrencyCode: String? = null): Result<BudgetAdviceResult>
}

/** Reads advice premises and routes explicit trial AI to the same freshness owner as saved advice. */
internal class BudgetAdviceInputsRepository(
    private val apiProvider: ApiServiceProvider,
    private val adviceCallStore: BudgetAdviceCallStore,
    private val errors: NetworkErrorHandler,
) : BudgetAdviceInputsActions {
    private val guard = LedgerRequestGuard(apiProvider)
    override suspend fun adviceInputs(expectedBinding: LogicalSessionBinding, month: String,
        homeCurrencyCode: String?): Result<BudgetAdviceInputsDto> = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        guard.bindExact(expectedBinding).call { it.budgetAdviceInputs(clean, currentBudgetTimezoneId(), homeCurrencyCode) }.also { result ->
            if (result.month != clean || (homeCurrencyCode != null && result.homeCurrencyCode != homeCurrencyCode) ||
                CurrencyCode.fromStorageKeyOrNull(result.homeCurrencyCode) == null ||
                result.missingRates.any { it.homeCurrencyCode != result.homeCurrencyCode }) {
                throw RepositoryException("budget_advice_inputs_unverified", localFailure = LocalRepositoryFailure.BudgetInputsUnverified)
            }
            adviceCallStore.noteAdviceInputSnapshot("budget_inputs:$expectedBinding:$clean:${result.homeCurrencyCode}:saved", result.toString())
        }
    }
    override suspend fun trialAdviceInputs(binding: LogicalSessionBinding, month: String,
        request: MonthlyArrangementSaveRequest, reportingHomeCurrencyCode: String?) = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val home = reportingHomeCurrencyCode ?: request.homeCurrencyCode
        val query = mutableMapOf("home_currency_code" to home, "savings_target_cents" to request.savingsTargetCents.toString(),
            "reserved_buffer_cents" to request.reservedBufferCents.toString())
        if (home != request.homeCurrencyCode) query["arrangement_currency_code"] = request.homeCurrencyCode
        guard.bindExact(binding).call { it.trialBudgetAdviceInputs(clean, currentBudgetTimezoneId(), query) }.also {
            require(it.month == clean && it.homeCurrencyCode == home && it.isTrial &&
                CurrencyCode.fromStorageKeyOrNull(home) != null && it.missingRates.all { gap -> gap.homeCurrencyCode == home })
            if (home == request.homeCurrencyCode) require(it.breakdown.savingsTargetCents == request.savingsTargetCents &&
                it.breakdown.reservedBufferCents == request.reservedBufferCents)
            else require(it.arrangementCurrencyCode == request.homeCurrencyCode)
            adviceCallStore.noteAdviceInputSnapshot("budget_inputs:$binding:$clean:$home:trial:${request.homeCurrencyCode}:${request.savingsTargetCents}:${request.reservedBufferCents}", it.toString())
        }
    }
    override suspend fun requestTrialAdvice(binding: LogicalSessionBinding, month: String,
        request: MonthlyArrangementSaveRequest, reportingHomeCurrencyCode: String?): Result<BudgetAdviceResult> {
        if (!ledgerRoleCanModify(apiProvider.currentLedgerRole())) return Result.failure(RepositoryException("当前角色为只读。"))
        return adviceCallStore.attachOrRequest(binding, validatedBudgetMonth(month).getOrElse { return Result.failure(it) },
            reportingHomeCurrencyCode ?: request.homeCurrencyCode, request)
    }
}
