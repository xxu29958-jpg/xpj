package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.MonthlyArrangementCacheDao
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

interface BudgetActions : BudgetSaveActions, ManualRateActions, MonthlyArrangementActions, BudgetAdviceInputsActions {
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

class BudgetRepository internal constructor(
    private val apiProvider: ApiServiceProvider,
    outbox: OutboxRepository,
    adapters: OutboxAdapterGraph,
    arrangementDao: MonthlyArrangementCacheDao,
    private val errorHandler: NetworkErrorHandler = budgetNetworkErrors(apiProvider),
    internal val adviceCallStore: BudgetAdviceCallStore = BudgetAdviceCallStore(LedgerRequestGuard(apiProvider), errorHandler),
) : BudgetActions, BudgetHistoryReader,
    BudgetSaveActions by BudgetSaveRepository(apiProvider, outbox, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter),
    ManualRateActions by ManualExchangeRateRepository(apiProvider, outbox, adapters.manualRateAdapter, adapters.manualRateReceiptAdapter),
    MonthlyArrangementActions by MonthlyArrangementRepository(apiProvider, outbox, arrangementDao,
        adapters.arrangementSaveAdapter, adapters.arrangementReceiptAdapter, adviceCallStore::noteAdviceInputSnapshot),
    BudgetAdviceInputsActions by BudgetAdviceInputsRepository(apiProvider, adviceCallStore, errorHandler) {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override suspend fun history(binding: LogicalSessionBinding, month: String, beforeVersion: Long?) =
        errorHandler.safeCall {
            val cleanMonth = validatedBudgetMonth(month).getOrThrow()
            ledgerRequestGuard.bindExact(binding).call { it.budgetHistory(cleanMonth, beforeVersion) }
                .also { require(it.ledgerId == binding.ledgerId && it.month == cleanMonth) }
                .toDomain()
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
        monthlyBudget(month, currentBudgetTimezoneId(), expectedBinding)

    suspend fun monthlyBudget(
        month: String,
        timezone: String,
        expectedBinding: LogicalSessionBinding? = null,
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

private fun budgetNetworkErrors(apiProvider: ApiServiceProvider) = NetworkErrorHandler(
    serverUrlProvider = { apiProvider.currentSession()?.serverUrl }, context = "Budget",
    statusMessages = mapOf(404 to "预算不存在。"),
)

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
