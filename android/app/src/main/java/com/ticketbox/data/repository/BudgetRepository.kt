package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions : BudgetSaveActions, ManualRateActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>

    /** One full binding/role projection for the advisor, including member-to-owner changes. */
    fun observeLedgerAccessState(): Flow<LedgerAccessState?> = emptyFlow()
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
    suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetMonthly>
    suspend fun requestBudgetAdvice(month: String, homeCurrencyCode: String? = null,
        expectedBinding: LogicalSessionBinding? = null): Result<BudgetAdviceResult>
    suspend fun adviceInputs(expectedBinding: LogicalSessionBinding, month: String,
        homeCurrencyCode: String? = null): Result<com.ticketbox.data.remote.dto.BudgetAdviceInputsDto>

    /** Advice is scoped to this process and logical binding; accepted writes invalidate it. */
    suspend fun cachedBudgetAdvice(month: String, homeCurrencyCode: String? = null): BudgetAdviceResult? = null

    /** Drops the process-lifetime advice cache (all bindings). */
    fun invalidateBudgetAdvice() { }

    /** Current advice data generation: bumps on every [invalidateBudgetAdvice].
     *  A live advice screen stamps its displayed result with the generation it
     *  was produced under and drops it when a newer generation arrives. */
    val adviceInvalidations: StateFlow<Int>
        get() = MutableStateFlow(0)
}

data class LedgerAccessState(
    val binding: LogicalSessionBinding,
    val role: String?,
) {
    val canModify: Boolean get() = ledgerRoleCanModify(role)
}

class BudgetRepository(
    private val apiProvider: ApiServiceProvider,
    outbox: OutboxRepository,
    saveAdapter: JsonAdapter<BudgetSavePayload>,
    receiptAdapter: JsonAdapter<BudgetMonthlyDto>,
    rateAdapter: JsonAdapter<ManualRatePayload>,
    rateReceiptAdapter: JsonAdapter<com.ticketbox.data.remote.dto.ExchangeRateDto>,
) : BudgetActions, BudgetSaveActions by BudgetSaveRepository(apiProvider, outbox, saveAdapter, receiptAdapter),
    ManualRateActions by ManualExchangeRateRepository(apiProvider, outbox, rateAdapter, rateReceiptAdapter) {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Budget",
        statusMessages = mapOf(404 to "预算不存在。"),
    )

    /** In-flight dedupe + process-lifetime advice cache + freshness tracking —
     *  extracted to [BudgetAdviceCallStore] (per-class function cap). internal
     *  so AppContainer can wire the refresh seams straight to the store. */
    internal val adviceCallStore = BudgetAdviceCallStore(ledgerRequestGuard, errorHandler)

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override suspend fun adviceInputs(expectedBinding: LogicalSessionBinding, month: String,
        homeCurrencyCode: String?): Result<com.ticketbox.data.remote.dto.BudgetAdviceInputsDto> = errorHandler.safeCall {
        val cleanMonth = validatedBudgetMonth(month).getOrThrow()
        ledgerRequestGuard.bindExact(expectedBinding).call {
            it.budgetAdviceInputs(cleanMonth, currentBudgetTimezoneId(), homeCurrencyCode)
        }.also { result ->
            if (result.month != cleanMonth || (homeCurrencyCode != null && result.homeCurrencyCode != homeCurrencyCode) ||
                com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(result.homeCurrencyCode) == null ||
                result.missingRates.any { it.homeCurrencyCode != result.homeCurrencyCode }) {
                throw RepositoryException("budget_advice_inputs_unverified", localFailure = LocalRepositoryFailure.BudgetInputsUnverified)
            }
            adviceCallStore.noteAdviceInputSnapshot("budget_inputs:$expectedBinding:$cleanMonth:${result.homeCurrencyCode}", result.toString())
        }
    }

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        apiProvider.observeActiveLedgerAccess()

    override fun observeLedgerAccessState(): Flow<LedgerAccessState?> =
        apiProvider.observeSession()
            .map { session ->
                val binding = session?.toBoundSessionSnapshotOrNull()?.logicalBinding ?: return@map null
                LedgerAccessState(binding, session.identity.role)
            }
            .distinctUntilChanged()

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> =
        monthlyBudget(month = month, timezone = currentBudgetTimezoneId())

    override suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetMonthly> =
        monthlyBudget(expectedBinding, month, currentBudgetTimezoneId())

    suspend fun monthlyBudget(month: String, timezone: String): Result<BudgetMonthly> {
        return monthlyBudget(expectedBinding = null, month = month, timezone = timezone)
    }

    private suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding?,
        month: String,
        timezone: String,
    ): Result<BudgetMonthly> {
        val cleanMonth = validatedBudgetMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val request = expectedBinding?.let(ledgerRequestGuard::bindExact)
                ?: ledgerRequestGuard.bind()
            request.call { api ->
                api.monthlyBudget(
                    month = cleanMonth,
                    timezone = timezone,
                ).toDomain()
            }
        }
    }

    override suspend fun requestBudgetAdvice(month: String, homeCurrencyCode: String?, expectedBinding: LogicalSessionBinding?): Result<BudgetAdviceResult> {
        if (!canModifyLedger()) {
            return Result.failure(
                RepositoryException(
                    message = "permission_denied",
                    errorCode = "permission_denied",
                ),
            )
        }
        val cleanMonth = validatedBudgetMonth(month)
            .getOrElse { return Result.failure(it) }
        // 218-B4 review: each live call is quota-counted server-side the moment
        // it starts. ONE logical-binding snapshot is captured up front and
        // scopes both the dedupe/cache key and the execution (the store's
        // bindExact re-validates it around the call).
        val binding = expectedBinding ?: ledgerRequestGuard.captureLogicalBinding()
            ?: return Result.failure(RepositoryException("登录状态已失效，请重新绑定。"))
        return adviceCallStore.attachOrRequest(binding, cleanMonth, homeCurrencyCode)
    }

    /** Process-lifetime last-successful advice for [month] under the CURRENT
     *  logical session binding — see [BudgetAdviceCallStore.cached]. */
    override suspend fun cachedBudgetAdvice(month: String, homeCurrencyCode: String?): BudgetAdviceResult? {
        val cleanMonth = validatedBudgetMonth(month)
            .getOrElse { return null }
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return null
        return adviceCallStore.cached(binding, cleanMonth, homeCurrencyCode)
    }

    override fun invalidateBudgetAdvice() = adviceCallStore.invalidate()

    override val adviceInvalidations: StateFlow<Int>
        get() = adviceCallStore.invalidations
}

internal fun currentBudgetTimezoneId(): String = TimeZone.getDefault().id

private val MONTH_PATTERN = Regex("^\\d{4}-\\d{2}$")

internal fun validatedBudgetMonth(month: String): Result<String> {
    return runCatching { requireMonth(month) }
        .fold(
            onSuccess = { Result.success(it) },
            onFailure = { Result.failure(RepositoryException(it.message ?: "预算月份不正确。")) },
        )
}

private fun requireMonth(month: String): String {
    val cleanMonth = month.trim()
    require(MONTH_PATTERN.matches(cleanMonth)) { "预算月份不正确。" }
    require(runCatching { YearMonth.parse(cleanMonth) }.isSuccess) { "预算月份不正确。" }
    return cleanMonth
}
