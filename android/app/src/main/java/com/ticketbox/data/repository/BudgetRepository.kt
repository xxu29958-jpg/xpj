package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
    suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult>

    /** Last successful advice for [month] in this process, or null. See
     *  [BudgetRepository.cachedBudgetAdvice] for the process-lifetime contract. */
    suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? = null

    suspend fun saveMonthlyBudget(month: String, update: BudgetMonthlyUpdate): Result<BudgetMonthly>
}

class BudgetRepository(
    private val apiProvider: ApiServiceProvider,
) : BudgetActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Budget",
        statusMessages = mapOf(404 to "预算不存在。"),
    )

    /** Guards [adviceInFlight] / [adviceLastSuccess]. Both are in-memory only —
     *  process-lifetime, never persisted (the advice round-trip persists
     *  nothing on device, see BudgetAdviseDto). Keyed by (ledger, month) so a
     *  ledger switch can never bleed another ledger's result in. */
    private val adviceCallMutex = Mutex()
    private val adviceInFlight = mutableMapOf<AdviceRequestKey, CompletableDeferred<Result<BudgetAdviceResult>>>()
    private val adviceLastSuccess = mutableMapOf<AdviceRequestKey, BudgetAdviceResult>()

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerId(): Flow<String?> = apiProvider.observeActiveLedgerId()

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> =
        monthlyBudget(month = month, timezone = currentTimezoneId())

    suspend fun monthlyBudget(month: String, timezone: String): Result<BudgetMonthly> {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
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
        // it starts, so concurrent callers (e.g. a reopened route while the
        // first call is still in flight) must attach to ONE in-flight call
        // instead of spending a second reservation.
        val key = adviceRequestKey(cleanMonth)
        val (deferred, isOwner) = adviceCallMutex.withLock {
            val existing = adviceInFlight[key]
            if (existing != null) {
                existing to false
            } else {
                val created = CompletableDeferred<Result<BudgetAdviceResult>>()
                adviceInFlight[key] = created
                created to true
            }
        }
        if (!isOwner) return deferred.await()
        return runAdviceCall(key, deferred, cleanMonth)
    }

    private suspend fun runAdviceCall(
        key: AdviceRequestKey,
        deferred: CompletableDeferred<Result<BudgetAdviceResult>>,
        month: String,
    ): Result<BudgetAdviceResult> = withContext(NonCancellable) {
        // NonCancellable: the page-scoped VM dies on route exit (viewModelScope
        // cancelled) while the backend may already have reserved the call.
        // Running to completion lets attached callers and the last-success
        // cache still observe the result instead of forcing a second call.
        val result = errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.budgetAdvise(
                    BudgetAdviseRequestDto(
                        month = month,
                        timezone = currentTimezoneId(),
                    ),
                ).toDomain()
            }
        }
        adviceCallMutex.withLock {
            result.getOrNull()?.let { adviceLastSuccess[key] = it }
            adviceInFlight.remove(key)
        }
        deferred.complete(result)
        result
    }

    /** Process-lifetime last-successful advice for [month] (and the active
     *  ledger), written only on success — a failure leaves the cache absent.
     *  Nothing is persisted; an app restart simply starts cold. */
    override suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return null }
        return adviceCallMutex.withLock {
            adviceLastSuccess[adviceRequestKey(cleanMonth)]
        }
    }

    override suspend fun saveMonthlyBudget(
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateMonthlyBudget(
                    month = cleanMonth,
                    request = update.toRequest(),
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    private fun adviceRequestKey(month: String): AdviceRequestKey = AdviceRequestKey(
        ledgerId = apiProvider.currentLedgerId().orEmpty(),
        month = month,
    )
}

private data class AdviceRequestKey(val ledgerId: String, val month: String)

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
