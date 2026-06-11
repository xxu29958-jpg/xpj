package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.security.SessionTokenStore
import retrofit2.Response
import java.io.IOException
import java.time.YearMonth
import java.util.TimeZone
import java.util.UUID

interface ReportsActions {
    fun canModifyLedger(): Boolean
    suspend fun reportsOverview(query: ReportsOverviewQuery = ReportsOverviewQuery()): Result<ReportsOverview>
    suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery = ReportsOverviewQuery()): Result<CsvExport>
    suspend fun goals(month: String? = null, includeArchived: Boolean = false): Result<List<Goal>>
    suspend fun createGoal(draft: GoalDraft): Result<Goal>
    suspend fun goal(publicId: String): Result<Goal>
    suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal>
    suspend fun archiveGoal(publicId: String): Result<Goal>
    suspend fun dashboardCards(surface: DashboardSurface = DashboardSurface.Android): Result<DashboardCards>
    suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface = DashboardSurface.Android,
    ): Result<DashboardCards>
}

class ReportsRepository(
    private val apiClient: ApiServiceFactory,
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore),
    /**
     * ADR-0042 Slice F: outbox surface for the offline-aware
     * [updateGoalAllowingOffline] entrypoint. ``null`` keeps every test
     * that doesn't wire the outbox at the old behaviour — the new method
     * falls back to the direct failure path when outbox/adapter aren't
     * both supplied. Mirrors [RuleRepository]'s nullable outbox wiring.
     */
    private val outbox: OutboxRepository? = null,
    private val goalUpdateAdapter: JsonAdapter<GoalUpdateRequestDto>? = null,
) : ReportsActions {
    private val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Reports",
        statusMessages = mapOf(404 to "没有找到目标。"),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    override suspend fun reportsOverview(query: ReportsOverviewQuery): Result<ReportsOverview> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.reportsOverview(
                    month = cleanQuery.month,
                    granularity = cleanQuery.granularity.apiValue,
                    topN = cleanQuery.topN,
                    merchantCategory = cleanQuery.merchantCategory,
                    rankingMetric = cleanQuery.rankingMetric.apiValue,
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery): Result<CsvExport> {
        val cleanQuery = query.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                val response = api.reportsOverviewCsv(
                    month = cleanQuery.month,
                    granularity = cleanQuery.granularity.apiValue,
                    topN = cleanQuery.topN,
                    merchantCategory = cleanQuery.merchantCategory,
                    rankingMetric = cleanQuery.rankingMetric.apiValue,
                    timezone = currentTimezoneId(),
                )
                val bytes = readExportBody(response)
                CsvExport(
                    fileName = "ticketbox-reports-overview-${cleanQuery.month ?: "current"}-${cleanQuery.granularity.apiValue}.csv",
                    bytes = bytes,
                )
            }
        }
    }

    override suspend fun goals(month: String?, includeArchived: Boolean): Result<List<Goal>> {
        val cleanMonth = month.cleanMonthOrNull()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.goals(
                    month = cleanMonth,
                    includeArchived = includeArchived,
                    timezone = currentTimezoneId(),
                ).items.map { it.toDomain() }
            }
        }
    }

    override suspend fun createGoal(draft: GoalDraft): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanDraft = draft.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.createGoal(
                    request = cleanDraft.toRequest(),
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    override suspend fun goal(publicId: String): Result<Goal> {
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.goal(
                    publicId = cleanPublicId,
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        val cleanUpdate = update.validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateGoal(
                    publicId = cleanPublicId,
                    request = cleanUpdate.toRequest(),
                    // ADR-0042: single-use key — direct-only path, no replay.
                    idempotencyKey = UUID.randomUUID().toString(),
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    /**
     * ADR-0042 Slice F: offline-aware version of [updateGoal]. Mirrors
     * [RuleRepository.updateCategoryRuleAllowingOffline] /
     * [MerchantRepository.updateMerchantAliasAllowingOffline].
     *
     * Direct PATCH first; on IOException AND with outbox wiring present,
     * enqueue an [PendingMutationType.UpdateGoal] row and return
     * [GoalSaveOutcome.Queued] with an optimistic projection. Any other
     * failure (4xx / 409 / 5xx HttpException) propagates to safeCall and
     * surfaces as Result.failure.
     *
     * Foundation-only in Slice F — no UI yet calls this (the goal-edit
     * screen doesn't exist). The method itself is the enqueue site the
     * outbox-coverage audit needs to consider [UpdateGoal] "wired".
     */
    suspend fun updateGoalAllowingOffline(
        baseline: Goal,
        update: GoalUpdate,
    ): Result<GoalSaveOutcome> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = baseline.publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        // Reuse the same validation as the direct path, then pin the token to
        // the baseline's row_version (the OCC anchor for this edit).
        val cleanUpdate = update.copy(expectedRowVersion = baseline.rowVersion).validated()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val request = cleanUpdate.toRequest()
            // [codex round-13 P1] Explicit bind so the IOException catch can
            // re-check session activity before enqueue — see RuleRepository.
            val bound = ledgerRequestGuard.bind()
            // ADR-0042: ONE intent-time key shared by the direct attempt and the
            // outbox replay. A committed-but-unseen PATCH replays with this SAME
            // key — the server HITs the recorded success instead of false-409ing
            // on the now-stale token. The dispatcher replays it from
            // row.idempotencyKey.
            val idempotencyKey = UUID.randomUUID().toString()
            val outboxRef = outbox
            val adapter = goalUpdateAdapter
            if (outboxRef == null || adapter == null) {
                // Wiring missing — direct-only; failures surface as Result.failure.
                val updated = bound.call { api ->
                    api.updateGoal(
                        publicId = cleanPublicId,
                        request = request,
                        idempotencyKey = idempotencyKey,
                        timezone = currentTimezoneId(),
                    ).toDomain()
                }
                return@safeCall GoalSaveOutcome.Synced(updated)
            }
            if (outboxRef.activeForTarget("goal:$cleanPublicId").isNotEmpty()) {
                // Per-target FIFO guard (codex follow-up review) — a direct
                // PATCH must not jump an unresolved queued mutation for the
                // same goal. Same mechanism as the expense:{id} guards.
                enqueueUpdateGoal(bound, outboxRef, adapter, cleanPublicId, request, baseline.rowVersion, idempotencyKey)
                return@safeCall GoalSaveOutcome.Queued(projectOptimisticGoal(baseline, cleanUpdate))
            }
            try {
                val updated = bound.call { api ->
                    api.updateGoal(
                        publicId = cleanPublicId,
                        request = request,
                        idempotencyKey = idempotencyKey,
                        timezone = currentTimezoneId(),
                    ).toDomain()
                }
                GoalSaveOutcome.Synced(updated) as GoalSaveOutcome
            } catch (networkError: IOException) {
                enqueueUpdateGoal(bound, outboxRef, adapter, cleanPublicId, request, baseline.rowVersion, idempotencyKey)
                GoalSaveOutcome.Queued(
                    projectOptimisticGoal(baseline, cleanUpdate),
                ) as GoalSaveOutcome
            }
        }
    }

    /**
     * Shared UpdateGoal enqueue for the queue-jump guard and the IOException
     * fallback. [codex round-13 P1] session race guard before enqueue +
     * [round-8 P3#5] payload token strip (row.expectedRowVersion is the
     * single source of truth; dispatcher overwrites on replay).
     */
    private suspend fun enqueueUpdateGoal(
        bound: BoundLedgerRequest,
        outboxRef: OutboxRepository,
        adapter: com.squareup.moshi.JsonAdapter<GoalUpdateRequestDto>,
        cleanPublicId: String,
        request: GoalUpdateRequestDto,
        token: Long,
        idempotencyKey: String,
    ) {
        bound.requireStillActive()
        outboxRef.enqueue(
            type = PendingMutationType.UpdateGoal,
            targetId = "goal:$cleanPublicId",
            payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
            expectedRowVersion = token,
            idempotencyKey = idempotencyKey,
        )
    }

    /**
     * Build the optimistic projection the UI shows while the queued PATCH
     * waits for connectivity. The user's submitted fields overwrite the
     * baseline; ``rowVersion`` / ``updatedAt`` stay at the pre-mutation
     * values (NOT server-confirmed tokens). Spend-derived fields
     * (spent/remaining/progress) are left as-is — the server recomputes them.
     */
    private fun projectOptimisticGoal(baseline: Goal, update: GoalUpdate): Goal =
        baseline.copy(
            name = update.name ?: baseline.name,
            month = update.month ?: baseline.month,
            targetAmountCents = update.targetAmountCents ?: baseline.targetAmountCents,
            category = update.category ?: baseline.category,
        )

    override suspend fun archiveGoal(publicId: String): Result<Goal> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = publicId.cleanPublicId()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.archiveGoal(
                    publicId = cleanPublicId,
                    timezone = currentTimezoneId(),
                ).toDomain()
            }
        }
    }

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.dashboardCards(surface = surface.apiValue).toDomain()
            }
        }

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanUpdates = updates.validatedDashboardUpdates()
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateDashboardCards(
                    request = cleanUpdates.toRequest(),
                    surface = surface.apiValue,
                ).toDomain()
            }
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id

    private fun readExportBody(response: Response<okhttp3.ResponseBody>): ByteArray {
        if (!response.isSuccessful) {
            val parsed = errorHandler.parseErrorMessage(response.code(), response.errorBody()?.string())
            throw RepositoryException(parsed.message, parsed.errorCode)
        }
        val body = response.body() ?: throw RepositoryException("导出内容为空。")
        return body.use { it.bytes() }
    }
}

/**
 * ADR-0042 Slice F sealed result for
 * [ReportsRepository.updateGoalAllowingOffline]. Mirrors
 * [CategoryRuleSaveOutcome] / [MerchantAliasSaveOutcome] — parallel-defined
 * so neither type's surface accidentally widens to the other's payload.
 */
sealed interface GoalSaveOutcome {
    val goal: Goal

    /** Server confirmed the PATCH; [goal] carries the canonical post-mutation token. */
    data class Synced(override val goal: Goal) : GoalSaveOutcome

    /**
     * Network failed; the mutation was persisted to the outbox and [goal] is
     * the optimistic projection (baseline merged with the user's submitted
     * fields). ``rowVersion`` is the pre-mutation token; chained POSTs must
     * not consume it.
     */
    data class Queued(override val goal: Goal) : GoalSaveOutcome
}

private val REPORTS_MONTH_PATTERN = Regex("^\\d{4}-\\d{2}$")

private fun ReportsOverviewQuery.validated(): Result<ReportsOverviewQuery> {
    return runCatching {
        copy(
            month = month.cleanMonthOrThrow("报表月份不正确。"),
            topN = topN.coerceIn(1, 20),
            merchantCategory = merchantCategory?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
        )
    }.mapError()
}

private fun GoalDraft.validated(): Result<GoalDraft> {
    return runCatching {
        val cleanName = name.trim()
        require(cleanName.isNotBlank()) { "请输入目标名称。" }
        require(targetAmountCents > 0L) { "目标金额必须大于 0。" }
        copy(
            name = cleanName,
            month = requireMonth(month, "目标月份不正确。"),
            category = category?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
        )
    }.mapError()
}

private fun GoalUpdate.validated(): Result<GoalUpdate> {
    return runCatching {
        if (name != null) {
            require(name.trim().isNotBlank()) { "请输入目标名称。" }
        }
        if (targetAmountCents != null) {
            require(targetAmountCents > 0L) { "目标金额必须大于 0。" }
        }
        copy(
            name = name?.trim(),
            month = month?.let { requireMonth(it, "目标月份不正确。") },
            category = category?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory),
        )
    }.mapError()
}

private fun List<DashboardCardUpdate>.validatedDashboardUpdates(): Result<List<DashboardCardUpdate>> {
    return runCatching {
        val clean = map {
            val key = it.key.trim()
            require(key.isNotBlank()) { "卡片类型不正确。" }
            require(it.position >= 0) { "卡片顺序不正确。" }
            it.copy(key = key)
        }
        require(clean.map { it.key }.distinct().size == clean.size) { "卡片不能重复。" }
        clean
    }.mapError()
}

private fun String.cleanPublicId(): Result<String> {
    return runCatching {
        trim().also { require(it.isNotBlank()) { "请选择一个目标。" } }
    }.mapError()
}

private fun String?.cleanMonthOrNull(): Result<String?> {
    return runCatching { cleanMonthOrThrow("月份不正确。") }.mapError()
}

private fun String?.cleanMonthOrThrow(errorMessage: String): String? {
    val cleanMonth = this?.trim()?.takeIf { it.isNotBlank() } ?: return null
    return requireMonth(cleanMonth, errorMessage)
}

private fun requireMonth(month: String, errorMessage: String): String {
    val cleanMonth = month.trim()
    require(REPORTS_MONTH_PATTERN.matches(cleanMonth)) { errorMessage }
    require(runCatching { YearMonth.parse(cleanMonth) }.isSuccess) { errorMessage }
    return cleanMonth
}

private fun <T> Result<T>.mapError(): Result<T> = fold(
    onSuccess = { Result.success(it) },
    onFailure = { Result.failure(RepositoryException(it.message ?: "请求参数不正确。")) },
)
