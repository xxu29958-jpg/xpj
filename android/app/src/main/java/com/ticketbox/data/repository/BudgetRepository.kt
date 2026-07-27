package com.ticketbox.data.repository

import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>

    /** Role projection of the active session identity: re-emits on ledger
     *  switches AND role-only re-projections (viewer↔member↔owner on the same
     *  ledger). Carries the full role — member→owner matters (the live
     *  advisor is owner-gated). */
    fun observeLedgerAccessState(): Flow<LedgerAccessState?> = emptyFlow()
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
    suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetMonthly>
    suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult>

    /** Last successful advice for [month] under the CURRENT logical session
     *  binding in this process, or null. Process-lifetime, binding-scoped —
     *  see [BudgetRepository.cachedBudgetAdvice]. Restored only while no
     *  advice-input write (income plan / recurring / budget / expense) has
     *  occurred in this process — those write paths call
     *  [invalidateBudgetAdvice] from their existing refresh points. */
    suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? = null

    /** Drops the process-lifetime advice cache (all bindings). */
    fun invalidateBudgetAdvice() { }

    suspend fun saveMonthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly>
}

data class LedgerAccessState(
    val ledgerId: String?,
    val role: String?,
)

class BudgetRepository(
    private val apiProvider: ApiServiceProvider,
) : BudgetActions {
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

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        apiProvider.observeActiveLedgerAccess()

    override fun observeLedgerAccessState(): Flow<LedgerAccessState?> =
        apiProvider.observeActiveLedgerIdentity()
            .map { identity ->
                LedgerAccessState(
                    ledgerId = identity?.ledgerId,
                    role = identity?.role,
                )
            }
            .distinctUntilChanged()

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> =
        monthlyBudget(month = month, timezone = currentTimezoneId())

    override suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetMonthly> =
        monthlyBudget(expectedBinding, month, currentTimezoneId())

    suspend fun monthlyBudget(month: String, timezone: String): Result<BudgetMonthly> {
        return monthlyBudget(expectedBinding = null, month = month, timezone = timezone)
    }

    private suspend fun monthlyBudget(
        expectedBinding: LogicalSessionBinding?,
        month: String,
        timezone: String,
    ): Result<BudgetMonthly> {
        val cleanMonth = validatedMonth(month)
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

    override suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult> {
        if (!canModifyLedger()) {
            return Result.failure(
                RepositoryException(
                    message = "permission_denied",
                    errorCode = "permission_denied",
                ),
            )
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        // 218-B4 review: each live call is quota-counted server-side the moment
        // it starts. ONE logical-binding snapshot is captured up front and
        // scopes both the dedupe/cache key and the execution (the store's
        // bindExact re-validates it around the call).
        val binding = ledgerRequestGuard.captureLogicalBinding()
            ?: return Result.failure(RepositoryException("登录状态已失效，请重新绑定。"))
        return adviceCallStore.attachOrRequest(binding, cleanMonth)
    }

    /** Process-lifetime last-successful advice for [month] under the CURRENT
     *  logical session binding — see [BudgetAdviceCallStore.cached]. */
    override suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return null }
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return null
        return adviceCallStore.cached(binding, cleanMonth)
    }

    override fun invalidateBudgetAdvice() = adviceCallStore.invalidate()

    override suspend fun saveMonthlyBudget(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.updateMonthlyBudget(
                    month = cleanMonth,
                    request = update.toRequest(),
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }
}

private fun currentTimezoneId(): String = TimeZone.getDefault().id

private val MONTH_PATTERN = Regex("^\\d{4}-\\d{2}$")

private fun validatedMonth(month: String): Result<String> {
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
