package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

/** Income management and the server's month-specific forecast; edits publish durable intent first. */
interface IncomePlanActions {
    fun canModifyLedger(): Boolean
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observeSubmissions(expectedBinding: LogicalSessionBinding): Flow<List<PendingIncomePlanSubmission>>
    fun describeSubmission(row: OutboxRow): PendingIncomePlanSubmission?
    suspend fun recoverSubmission(expectedBinding: LogicalSessionBinding, pending: PendingIncomePlanSubmission, drop: Boolean): Result<Unit>
    suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing>
    suspend fun listIncluding(expectedBinding: LogicalSessionBinding, status: IncomePlanStatus): Result<List<IncomePlan>>
    suspend fun create(expectedBinding: LogicalSessionBinding, draft: IncomePlanDraft): Result<Long>
    suspend fun enqueueUpdate(expectedBinding: LogicalSessionBinding, baseline: IncomePlan,
        patch: IncomePlanPatch, currency: CurrencyCode): Result<Long>
    suspend fun archive(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan>
    suspend fun restore(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan>
}

data class IncomePlanListing(
    val plans: List<IncomePlan>,
    val expectedAmountCents: Long?,
    val month: String,
    val scheduledAmountCents: Long?,
    val effectivePlanCount: Int,
    val homeCurrencyCode: String? = null,
    val missingCurrencyCodes: List<String> = emptyList(),
    val referenceRates: List<com.ticketbox.domain.model.CurrencyReferenceRate> = emptyList(),
)

class IncomePlanRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val incomePlanSubmissionAdapter: JsonAdapter<IncomePlanSubmissionPayload>,
    private val incomePlanReceiptAdapter: JsonAdapter<IncomePlanDto>,
) : IncomePlanActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "IncomePlan",
        statusMessages = mapOf(404 to "收入计划不存在。", 409 to "计划已发生变化，请刷新后核对。",
            422 to "请检查计划月份、金额和预计日期。"))

    override fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())
    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override fun describeSubmission(row: OutboxRow): PendingIncomePlanSubmission? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type !in INCOME_SUBMISSION_TYPES || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(binding.serverUrl)) return null
        val intent = runCatching { incomePlanSubmissionAdapter.fromJson(row.payloadJson) }.getOrNull()
        val receipt = row.receiptJson?.let { runCatching { incomePlanReceiptAdapter.fromJson(it) }.getOrNull() }
        return PendingIncomePlanSubmission(row, intent, receipt?.takeIf { intent?.acceptsReceipt(row, it) == true }?.toDomain())
    }

    override fun observeSubmissions(expectedBinding: LogicalSessionBinding): Flow<List<PendingIncomePlanSubmission>> =
        outbox.observeActiveByTypes(INCOME_SUBMISSION_TYPES, includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != expectedBinding) emptyList() else rows.mapNotNull(::describeSubmission)
        }

    override suspend fun recoverSubmission(expectedBinding: LogicalSessionBinding, pending: PendingIncomePlanSubmission,
        drop: Boolean): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(expectedBinding)
        val current = observeSubmissions(expectedBinding).first().firstOrNull { it.row.id == pending.row.id }?.row
        require(current == pending.row) { "原收入提交状态已变化，请重新核对。" }
        val original = requireNotNull(describeSubmission(requireNotNull(current)))
        require(if (drop) original.canDrop else original.canRetry && canModifyLedger()) { "请先核对原收入提交。" }
        val changed = when (current.status) {
            PendingMutationStatus.Done -> outbox.discardCompletedOriginalSubmission(bound, current)
            PendingMutationStatus.Conflict -> outbox.resolveConflict(current.id, ConflictResolution.DropMine, bound)
            else -> outbox.resolveFailed(current.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
        }
        check(changed) { "原收入提交状态已变化，请重新核对。" }
    }

    override suspend fun listActive(expectedBinding: LogicalSessionBinding): Result<IncomePlanListing> = errors.safeCall {
        guard.bindExact(expectedBinding).call { api ->
            val response = api.listIncomePlans(status = "active")
            IncomePlanListing(response.items.map { it.toDomain() }, response.expectedAmountCents,
                response.month, response.scheduledAmountCents, response.effectivePlanCount,
                response.homeCurrencyCode, response.missingCurrencyCodes, response.referenceRates.map { it.toDomain() })
        }
    }.onSuccess { listing ->
        onActivePlansSnapshot("m=${listing.month};home=${listing.homeCurrencyCode};total=${listing.expectedAmountCents};" +
            "n=${listing.plans.size};rv=${listing.plans.maxOfOrNull(IncomePlan::rowVersion) ?: 0};" +
            "ua=${listing.plans.maxOfOrNull(IncomePlan::updatedAt).orEmpty()}")
    }

    /** Invalidates advice on a changed confirmed forecast or management snapshot. */
    var onActivePlansSnapshot: (stamp: String) -> Unit = {}

    override suspend fun listIncluding(expectedBinding: LogicalSessionBinding,
        status: IncomePlanStatus): Result<List<IncomePlan>> = errors.safeCall {
        guard.bindExact(expectedBinding).call { it.listIncomePlans(status = status.wireValue).items.map { row -> row.toDomain() } }
    }

    override suspend fun create(expectedBinding: LogicalSessionBinding, draft: IncomePlanDraft): Result<Long> = errors.safeCall {
        require(canModifyLedger()) { "当前角色为只读，无法修改账本。" }
        val bound = guard.bindExact(expectedBinding)
        val request = draft.toCreateRequest()
        val payload = IncomePlanSubmissionPayload(INCOME_PLAN_CREATE_PAYLOAD_REVISION, "", request.label,
            request.amountCents, request.homeCurrencyCode, expectedBinding.sessionGeneration, expectedBinding.bindingRevision,
            IncomePlanUpdateRequestDto(request.intentMonth, 0, request.label, request.sourceType, request.frequency,
                request.incomeMonth, request.amountCents, request.payDay))
        val key = UUID.randomUUID().toString()
        outbox.enqueue(boundRequest = bound, intent = payload.toMutationIntent(incomePlanSubmissionAdapter, 0, key),
            validateTargetRows = ::requireIncomeTargetSettled)
    }

    override suspend fun enqueueUpdate(expectedBinding: LogicalSessionBinding, baseline: IncomePlan,
        patch: IncomePlanPatch, currency: CurrencyCode): Result<Long> = errors.safeCall {
        if (!canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账本。")
        val bound = guard.bindExact(expectedBinding)
        require(baseline.rowVersion > 0) { "请刷新计划后重新核对修改。" }
        if (outbox.activeForTarget(bound, incomePlanTarget(baseline.publicId)).isNotEmpty()) {
            throw RepositoryException("这条计划有待处理的修改，请先查看原提交的同步结果。")
        }
        if (patch.expectedRowVersion != baseline.rowVersion) throw RepositoryException("请刷新计划后重新核对修改。")
        if (baseline.homeCurrencyCode != currency.storageKey) throw RepositoryException("计划币种还无法确认，请刷新计划后核对金额。")
        val payload = IncomePlanSubmissionPayload(INCOME_PLAN_EDIT_PAYLOAD_REVISION, baseline.publicId, baseline.label,
            baseline.amountCents, currency.storageKey, expectedBinding.sessionGeneration, expectedBinding.bindingRevision,
            patch.toUpdateRequest().copy(expectedRowVersion = 0))
        outbox.enqueue(boundRequest = bound, intent = payload.toMutationIntent(incomePlanSubmissionAdapter,
            baseline.rowVersion, UUID.randomUUID().toString()), validateTargetRows = ::requireIncomeTargetSettled)
    }

    override suspend fun archive(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan> = errors.safeCall {
        if (!canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账本。")
        val bound = guard.bindExact(expectedBinding)
        requireIncomeTargetSettled(outbox.activeForTarget(bound, incomePlanTarget(publicId)))
        bound.call {
            it.archiveIncomePlan(publicId, IncomePlanTokenRequestDto(expectedRowVersion, intentMonth)).toDomain()
        }
    }

    override suspend fun restore(expectedBinding: LogicalSessionBinding, publicId: String,
        expectedRowVersion: Long, intentMonth: String): Result<IncomePlan> = errors.safeCall {
        if (!canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账本。")
        val bound = guard.bindExact(expectedBinding)
        requireIncomeTargetSettled(outbox.activeForTarget(bound, incomePlanTarget(publicId)))
        bound.call {
            it.restoreIncomePlan(publicId, IncomePlanTokenRequestDto(expectedRowVersion, intentMonth)).toDomain()
        }
    }

}

private val INCOME_SUBMISSION_TYPES = setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan)

private fun requireIncomeTargetSettled(rows: List<OutboxRow>) {
    require(rows.none { it.status != PendingMutationStatus.Done }) {
        "这条计划有待处理的提交，请先核对同步结果。"
    }
}
