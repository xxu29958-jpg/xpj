package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import java.time.YearMonth
import java.util.TimeZone
import java.util.UUID

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

    /** Advice is scoped to this process and logical binding; accepted writes invalidate it. */
    suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? = null

    /** Drops the process-lifetime advice cache (all bindings). */
    fun invalidateBudgetAdvice() { }

    /** Current advice data generation: bumps on every [invalidateBudgetAdvice].
     *  A live advice screen stamps its displayed result with the generation it
     *  was produced under and drops it when a newer generation arrives. */
    val adviceInvalidations: StateFlow<Int>
        get() = MutableStateFlow(0)

    fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<PendingBudgetSave>>
    suspend fun recoverSave(expectedBinding: LogicalSessionBinding, pending: PendingBudgetSave, drop: Boolean): Result<Unit>
    suspend fun enqueueSave(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<Long>
}

data class LedgerAccessState(
    val ledgerId: String?,
    val role: String?,
)

class BudgetRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val saveAdapter: JsonAdapter<BudgetSavePayload>,
    private val receiptAdapter: JsonAdapter<BudgetMonthlyDto>,
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

    override val adviceInvalidations: StateFlow<Int>
        get() = adviceCallStore.invalidations

    override fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<PendingBudgetSave>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.SaveMonthlyBudget), includeCompleted = true).map { rows ->
            if (ledgerRequestGuard.captureLogicalBinding() != expectedBinding) emptyList()
            else rows.mapNotNull(::describeSave)
        }

    fun describeSave(row: OutboxRow): PendingBudgetSave? {
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.SaveMonthlyBudget ||
            row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId) return null
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it)?.toDomain() }.getOrNull() }
        return PendingBudgetSave(row, saveAdapter.readSupportedBudgetSave(row.payloadJson), receipt)
    }

    override suspend fun recoverSave(expectedBinding: LogicalSessionBinding, pending: PendingBudgetSave, drop: Boolean): Result<Unit> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expectedBinding)
        check(pending.row.type == PendingMutationType.SaveMonthlyBudget && (drop || pending.intent != null)) {
            "无法确认原预算提交的格式，请保留记录并核对。"
        }
        when (pending.row.status) {
            PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(pending.row.id, ConflictResolution.DropMine, bound)
            PendingMutationStatus.Failed -> outbox.resolveFailed(pending.row.id,
                if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
            else -> Unit
        }
        Unit
    }

    override suspend fun enqueueSave(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<Long> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanMonth = validatedMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expectedBinding)
            check(CurrencyCode.fromStorageKeyOrNull(update.homeCurrencyCode) != null) { "预算币种无法确认，请重新读取预算。" }
            check(update.expectedRowVersion == null || update.expectedRowVersion > 0) { "预算版本无法确认，请重新读取预算。" }
            val payload = BudgetSavePayload(1, cleanMonth, currentTimezoneId(), update.toRequest().copy(expectedRowVersion = null))
            outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
                type = PendingMutationType.SaveMonthlyBudget, targetId = monthlyBudgetTarget(cleanMonth),
                payloadJson = saveAdapter.toJson(payload), expectedRowVersion = update.expectedRowVersion ?: 0L,
                idempotencyKey = UUID.randomUUID().toString()), validateTargetRows = { rows ->
                    check(rows.isEmpty()) { "这月预算有待处理的保存，请先查看原提交的同步结果。" }
                })
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
