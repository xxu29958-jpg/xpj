package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

interface SplitAgreementActions {
    suspend fun load(task: DebtTask, share: Long? = null): Result<BillSplitAgreementDto>
    suspend fun submit(task: DebtTask, intent: SplitAgreementPayload): Result<Long>
    fun describe(row: OutboxRow): SplitAgreementPayload?
    fun observe(task: DebtTask): Flow<List<OutboxRow>>
    suspend fun recover(task: DebtTask, row: OutboxRow, drop: Boolean): Result<Unit>
}

class SplitAgreementRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val adapter: JsonAdapter<SplitAgreementPayload>,
) : SplitAgreementActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "SplitAgreement")

    override suspend fun load(task: DebtTask, share: Long?): Result<BillSplitAgreementDto> = errors.safeCall {
        guard.bindExact(task.binding).call { it.splitAgreement(task.debtPublicId, share) }
    }

    override suspend fun submit(task: DebtTask, intent: SplitAgreementPayload): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(task.binding)
        require(task.debtPublicId == intent.originalDebtPublicId) { "请回到原往来核对新约定。" }
        val payload = adapter.toJson(intent)
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
            PendingMutationType.SplitAgreement, debtWriteTarget(intent.originalDebtPublicId), payload,
            intent.expectedRowVersion, UUID.randomUUID().toString()), validateTargetRows = { rows ->
            require(rows.none { it.status != PendingMutationStatus.Done }) { "请先处理这段往来的原提交。" }
        })
    }

    override fun describe(row: OutboxRow): SplitAgreementPayload? = adapter.readSplitAgreement(row)

    override fun observe(task: DebtTask): Flow<List<OutboxRow>> = outbox.observeActiveByTypes(
        setOf(PendingMutationType.SplitAgreement), includeCompleted = true,
    ).map { rows ->
        if (guard.captureLogicalBinding() != task.binding) emptyList()
        else rows.filter { (it.targetId == debtWriteTarget(task.debtPublicId) ||
            describe(it)?.returnDebtPublicId == task.debtPublicId) &&
            it.ownerKey == task.binding.ownerKey && it.ledgerId == task.binding.ledgerId }
    }

    override suspend fun recover(task: DebtTask, row: OutboxRow, drop: Boolean): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(task.binding)
        val current = outbox.activeForTarget(bound, debtWriteTarget(task.debtPublicId)).singleOrNull { it.id == row.id }
            ?: throw RepositoryException("原提交状态已变化，请重新查看。")
        require(current.type == PendingMutationType.SplitAgreement)
        require(drop || adapter.readSplitAgreement(current) != null)
        val changed = when (current.status) {
            PendingMutationStatus.Conflict -> {
                require(drop) { "约定依据已变化，请保留草稿并重新预览后发起。" }
                outbox.resolveConflict(current.id, ConflictResolution.DropMine, boundRequest = bound)
            }
            PendingMutationStatus.Failed -> outbox.resolveFailed(current.id,
                if (drop) FailedResolution.Drop else FailedResolution.Retry(), boundRequest = bound)
            else -> false
        }
        require(changed) { "请等待原提交处理完成。" }
    }
}
