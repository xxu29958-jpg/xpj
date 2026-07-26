package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import java.time.YearMonth
import java.util.TimeZone

interface BudgetActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()

    /** Access projection of the active session identity: re-emits on ledger
     *  switches AND role-only re-projections (viewer↔member↔owner on the same
     *  ledger), which [observeActiveLedgerId] cannot distinguish. Carries the
     *  full role — member→owner matters (the live advisor is owner-gated). */
    fun observeLedgerAccessState(): Flow<LedgerAccessState?> = emptyFlow()
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
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

    suspend fun saveMonthlyBudget(month: String, update: BudgetMonthlyUpdate): Result<BudgetMonthly>
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

    /** Guards [adviceInFlight] / [adviceLastSuccess]; a plain monitor because
     *  every critical section below is non-suspending map I/O — that keeps
     *  [invalidateBudgetAdvice] callable from non-suspend refresh callbacks.
     *  Both maps are in-memory only — process-lifetime, never persisted (the
     *  advice round-trip persists nothing on device, see BudgetAdviseDto).
     *  Keyed by (logical session binding, month): the binding carries
     *  server/account/ledger/generation, so an unbind + re-pair to a different
     *  household — even one whose ledger id is also "owner" — can never be
     *  served another binding's result. */
    private val adviceCacheLock = Any()
    private val adviceInFlight = mutableMapOf<AdviceRequestKey, CompletableDeferred<Result<BudgetAdviceResult>>>()
    private val adviceLastSuccess = mutableMapOf<AdviceRequestKey, BudgetAdviceResult>()

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerId(): Flow<String?> = apiProvider.observeActiveLedgerId()

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
        // instead of spending a second reservation. ONE logical-binding
        // snapshot is captured up front and scopes both the dedupe/cache key
        // and the execution (bindExact re-validates it around the call).
        val binding = ledgerRequestGuard.captureLogicalBinding()
            ?: return Result.failure(RepositoryException("登录状态已失效，请重新绑定。"))
        val key = AdviceRequestKey(binding = binding, month = cleanMonth)
        val (deferred, isOwner) = synchronized(adviceCacheLock) {
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
            ledgerRequestGuard.bindExact(key.binding).call { api ->
                api.budgetAdvise(
                    BudgetAdviseRequestDto(
                        month = month,
                        timezone = currentTimezoneId(),
                    ),
                ).toDomain()
            }
        }
        synchronized(adviceCacheLock) {
            // Only a real advice payload is cached: a null-advice result (e.g.
            // provider_empty) must never be restored, or a later operator-side
            // fix would stay invisible behind the cached terminal state.
            result.getOrNull()
                ?.takeIf { it.advice != null }
                ?.let { adviceLastSuccess[key] = it }
            adviceInFlight.remove(key)
        }
        deferred.complete(result)
        result
    }

    /** Process-lifetime last-successful advice for [month] under the CURRENT
     *  logical session binding, written only on a success that carries an
     *  actual advice payload — failures and null-advice results leave the
     *  cache absent. Nothing is persisted; an app restart simply starts cold.
     *  The binding is part of the lookup key, so a re-paired household never
     *  sees a previous binding's entry. */
    override suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? {
        val cleanMonth = validatedMonth(month)
            .getOrElse { return null }
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return null
        return synchronized(adviceCacheLock) {
            adviceLastSuccess[AdviceRequestKey(binding = binding, month = cleanMonth)]
        }
    }

    override fun invalidateBudgetAdvice() {
        synchronized(adviceCacheLock) {
            adviceLastSuccess.clear()
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
}

private data class AdviceRequestKey(
    val binding: LogicalSessionBinding,
    val month: String,
)

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
