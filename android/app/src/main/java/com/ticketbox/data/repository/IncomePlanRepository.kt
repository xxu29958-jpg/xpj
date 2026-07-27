package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import java.io.IOException
import java.util.UUID

/**
 * v1.1 monthly income plan repository. CRUD over /api/income-plans plus
 * an "active total" aggregate that the budget overview card surfaces.
 *
 * Failure semantics follow the rest of the repository layer: every
 * suspend method returns ``Result<T>``; viewer role short-circuits
 * write calls without hitting the network.
 */
interface IncomePlanActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing>
    suspend fun listIncluding(
        expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus,
    ): Result<List<IncomePlan>>
    suspend fun create(
        expectedBinding: LogicalSessionBinding,
        draft: IncomePlanDraft,
    ): Result<IncomePlan>
    suspend fun update(publicId: String, patch: IncomePlanPatch): Result<IncomePlan>

    /**
     * ADR-0042 Slice F: offline-aware update. Direct PATCH first; on
     * IOException with outbox wiring present, enqueue and return
     * [IncomePlanSaveOutcome.Queued]. Default throws so test doubles that
     * don't implement it still compile against the old surface — the
     * production [IncomePlanRepository] overrides it.
     */
    suspend fun updateAllowingOffline(
        baseline: IncomePlan,
        patch: IncomePlanPatch,
    ): Result<IncomePlanSaveOutcome> =
        throw NotImplementedError("updateAllowingOffline not wired in this IncomePlanActions")

    suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan>
    suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan>
}

data class IncomePlanListing(
    val plans: List<IncomePlan>,
    val totalActiveAmountCents: Long,
)

class IncomePlanRepository(
    private val apiProvider: ApiServiceProvider,
    /**
     * ADR-0042 Slice F: outbox surface for [updateAllowingOffline]. ``null``
     * keeps every test that doesn't wire the outbox at the old direct-only
     * behaviour. Mirrors [RuleRepository]'s nullable outbox wiring.
     */
    private val outbox: OutboxRepository? = null,
    private val incomePlanUpdateAdapter: JsonAdapter<IncomePlanUpdateRequestDto>? = null,
) : IncomePlanActions {

    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "IncomePlan",
        statusMessages = mapOf(
            404 to "收入计划不存在。",
            409 to "已归档的收入计划不能直接修改，请先恢复。",
            422 to "请检查输入的金额和发薪日。",
        ),
    )

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> =
        apiProvider.observeActiveLedgerAccess()

    override suspend fun listActive(
        expectedBinding: LogicalSessionBinding,
    ): Result<IncomePlanListing> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                val response = api.listIncomePlans(status = "active")
                IncomePlanListing(
                    plans = response.items.map { it.toDomain() },
                    totalActiveAmountCents = response.totalActiveAmountCents,
                )
            }
        }.onSuccess { listing ->
            // The advisor consumes the active income-plan set; fire-and-forget
            // seam, var per the onConfirmedCommitted precedent.
            onActivePlansSnapshot(
                "n=${listing.plans.size};" +
                    "rv=${listing.plans.maxOfOrNull(IncomePlan::rowVersion) ?: 0};" +
                    "ua=${listing.plans.maxOfOrNull(IncomePlan::updatedAt).orEmpty()}",
            )
        }

    /** Fired with a cheap stable stamp after each successful active-plans
     *  fetch. Wired in AppContainer to the budget-advice freshness sink. */
    var onActivePlansSnapshot: (stamp: String) -> Unit = {}

    override suspend fun listIncluding(
        expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus,
    ): Result<List<IncomePlan>> =
        errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.listIncomePlans(status = status.wireValue)
                    .items.map { it.toDomain() }
            }
        }

    override suspend fun create(
        expectedBinding: LogicalSessionBinding,
        draft: IncomePlanDraft,
    ): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.createIncomePlan(draft.toCreateRequest()).toDomain()
            }
        }
    }

    override suspend fun update(
        publicId: String,
        patch: IncomePlanPatch,
    ): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.guardedCall { api ->
                api.updateIncomePlan(
                    publicId,
                    patch.toUpdateRequest(),
                    // ADR-0042: single-use key — direct-only path, no replay.
                    UUID.randomUUID().toString(),
                ).toDomain()
            }
        }
    }

    /**
     * ADR-0042 Slice F: offline-aware version of [update]. Mirrors
     * [RuleRepository.updateCategoryRuleAllowingOffline] /
     * [MerchantRepository.updateMerchantAliasAllowingOffline].
     *
     * Direct PATCH first; on IOException AND with outbox wiring present,
     * enqueue an [PendingMutationType.UpdateIncomePlan] row and return
     * [IncomePlanSaveOutcome.Queued] with an optimistic projection. Any other
     * failure (4xx / 409 / 5xx HttpException) propagates and surfaces as
     * Result.failure.
     *
     * Foundation-only in Slice F — no UI yet calls this (there's no income-plan
     * edit caller). The method itself is the enqueue site the outbox-coverage
     * audit needs to consider [UpdateIncomePlan] "wired".
     */
    override suspend fun updateAllowingOffline(
        baseline: IncomePlan,
        patch: IncomePlanPatch,
    ): Result<IncomePlanSaveOutcome> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanPublicId = baseline.publicId.trim()
        if (cleanPublicId.isEmpty()) {
            return Result.failure(RepositoryException("请选择一个收入计划。"))
        }
        // Pin the OCC token to the baseline's row_version for this edit.
        val request = patch.copy(expectedRowVersion = baseline.rowVersion).toUpdateRequest()
        return errorHandler.safeCall {
            // [codex round-13 P1] Explicit bind so the IOException catch can
            // re-check session activity before enqueue — see RuleRepository.
            val bound = ledgerRequestGuard.bind()
            // ADR-0042: ONE intent-time key shared by the direct attempt and the
            // outbox replay — see updateCategoryRuleAllowingOffline.
            val idempotencyKey = UUID.randomUUID().toString()
            val outboxRef = outbox
            val adapter = incomePlanUpdateAdapter
            if (outboxRef == null || adapter == null) {
                // Wiring missing — direct-only; failures surface as Result.failure.
                val updated = bound.call { api ->
                    api.updateIncomePlan(cleanPublicId, request, idempotencyKey).toDomain()
                }
                return@safeCall IncomePlanSaveOutcome.Synced(updated)
            }
            val enqueueContext = IncomePlanOutboxContext(
                bound = bound,
                outbox = outboxRef,
                cleanPublicId = cleanPublicId,
                token = baseline.rowVersion,
                idempotencyKey = idempotencyKey,
            )
            if (outboxRef.activeForTarget(bound, enqueueContext.targetId).isNotEmpty()) {
                // Per-target FIFO guard (codex follow-up review) — a direct
                // PATCH must not jump an unresolved queued mutation for the
                // same plan. Same mechanism as the expense:{id} guards.
                enqueueUpdateIncomePlan(enqueueContext, adapter, request)
                return@safeCall IncomePlanSaveOutcome.Queued(projectOptimisticPlan(baseline, patch))
            }
            try {
                val updated = bound.call { api ->
                    api.updateIncomePlan(cleanPublicId, request, idempotencyKey).toDomain()
                }
                IncomePlanSaveOutcome.Synced(updated) as IncomePlanSaveOutcome
            } catch (networkError: IOException) {
                enqueueUpdateIncomePlan(enqueueContext, adapter, request)
                IncomePlanSaveOutcome.Queued(
                    projectOptimisticPlan(baseline, patch),
                ) as IncomePlanSaveOutcome
            }
        }
    }

    /**
     * Shared UpdateIncomePlan enqueue for the queue-jump guard and the
     * IOException fallback. [codex round-13 P1] session race guard before
     * enqueue + [round-8 P3#5] payload token strip (row.expectedRowVersion
     * is the single source of truth; dispatcher overwrites on replay).
     */
    private suspend fun enqueueUpdateIncomePlan(
        context: IncomePlanOutboxContext,
        adapter: JsonAdapter<IncomePlanUpdateRequestDto>,
        request: IncomePlanUpdateRequestDto,
    ) {
        context.outbox.enqueue(
            boundRequest = context.bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.UpdateIncomePlan,
                targetId = context.targetId,
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = context.token,
                idempotencyKey = context.idempotencyKey,
            ),
        )
    }

    /**
     * Build the optimistic projection the UI shows while the queued PATCH
     * waits for connectivity. The user's submitted fields overwrite the
     * baseline; ``rowVersion`` / ``updatedAt`` stay at the pre-mutation
     * values (NOT server-confirmed tokens).
     */
    private fun projectOptimisticPlan(baseline: IncomePlan, patch: IncomePlanPatch): IncomePlan =
        (patch.frequency ?: baseline.frequency).let { nextFrequency ->
            baseline.copy(
                label = patch.label?.trim()?.takeIf { it.isNotBlank() } ?: baseline.label,
                sourceType = patch.sourceType ?: baseline.sourceType,
                frequency = nextFrequency,
                incomeMonth = when {
                    nextFrequency == IncomeFrequency.MONTHLY -> null
                    patch.incomeMonth != null -> patch.incomeMonth
                    else -> baseline.incomeMonth
                },
                amountCents = patch.amountCents ?: baseline.amountCents,
                payDay = patch.payDay ?: baseline.payDay,
            )
        }

    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.archiveIncomePlan(
                    publicId,
                    com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto(expectedRowVersion),
                ).toDomain()
            }
        }
    }

    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<IncomePlan> {
        if (!canModifyLedger()) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        return errorHandler.safeCall {
            ledgerRequestGuard.bindExact(expectedBinding).call { api ->
                api.restoreIncomePlan(
                    publicId,
                    com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto(expectedRowVersion),
                ).toDomain()
            }
        }
    }
}

/**
 * ADR-0042 Slice F sealed result for
 * [IncomePlanRepository.updateAllowingOffline]. Mirrors
 * [CategoryRuleSaveOutcome] / [MerchantAliasSaveOutcome] / [GoalSaveOutcome]
 * — parallel-defined so neither type's surface accidentally widens to the
 * other's payload.
 */
sealed interface IncomePlanSaveOutcome {
    val plan: IncomePlan

    /** Server confirmed the PATCH; [plan] carries the canonical post-mutation token. */
    data class Synced(override val plan: IncomePlan) : IncomePlanSaveOutcome

    /**
     * Network failed; the mutation was persisted to the outbox and [plan] is
     * the optimistic projection (baseline merged with the user's submitted
     * fields). ``rowVersion`` is the pre-mutation token; chained POSTs must
     * not consume it.
     */
    data class Queued(override val plan: IncomePlan) : IncomePlanSaveOutcome
}

private data class IncomePlanOutboxContext(
    val bound: BoundLedgerRequest,
    val outbox: OutboxRepository,
    val cleanPublicId: String,
    val token: Long,
    val idempotencyKey: String,
) {
    val targetId: String = "income_plan:$cleanPublicId"
}
