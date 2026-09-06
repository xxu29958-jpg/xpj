package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

interface DebtAdjustmentActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observeAdjustments(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingDebtAdjustment>>
    fun describeAdjustment(row: OutboxRow): PendingDebtAdjustment?
    suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtAdjustment, drop: Boolean): Result<Unit>
}

/** Publishes local intent; only RecordDebtAdjustmentDispatcher sends the existing backend command. */
class DebtAdjustmentRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val adapter: JsonAdapter<DebtAdjustmentPayload>,
) : DebtAdjustmentActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Debt adjustment")

    override fun currentAccess(): LedgerAccessContext? = guard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, ledgerRoleCanModify(apiProvider.currentLedgerRole()))
    }

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override fun describeAdjustment(row: OutboxRow): PendingDebtAdjustment? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.RecordDebtAdjustment ||
            row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId
        ) return null
        return row.describeDebtAdjustment(adapter)
    }

    override fun observeAdjustments(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingDebtAdjustment>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.RecordDebtAdjustment), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList()
            else rows.filter { it.targetId == debtAdjustmentTarget(publicId) }.mapNotNull(::describeAdjustment)
        }

    override suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long> =
        errors.safeCall {
            val bound = guard.bindExact(binding)
            if (currentAccess()?.canModify != true) throw RepositoryException("当前角色为只读，无法修改账本。")
            require(debt.ledgerId == binding.ledgerId && debt.isDirectWritable && !debt.isVoided) { "这笔欠款不能直接调整。" }
            require(CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode) != null) { "当前版本不支持这笔欠款的币种。" }
            require(amountCents != 0L && reason.isNotBlank() && debt.rowVersion > 0L) { "请填写调整金额和原因。" }
            if (outbox.activeForTarget(bound, debtAdjustmentTarget(debt.publicId)).isNotEmpty()) {
                throw RepositoryException("这笔欠款还有待处理的调整，请先核对原提交。")
            }
            val payload = DebtAdjustmentPayload(
                revision = 1,
                subject = DebtAdjustmentSubject(debt.publicId, debt.counterpartyLabel, debt.homeCurrencyCode),
                originSessionGeneration = binding.sessionGeneration,
                originBindingRevision = binding.bindingRevision,
                request = DebtAdjustmentCreateRequestDto(amountCents, reason.trim(), debt.rowVersion),
            )
            outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
                type = PendingMutationType.RecordDebtAdjustment, targetId = debtAdjustmentTarget(debt.publicId),
                payloadJson = adapter.toJson(payload), expectedRowVersion = debt.rowVersion,
                idempotencyKey = UUID.randomUUID().toString(),
            ))
        }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtAdjustment, drop: Boolean): Result<Unit> =
        errors.safeCall {
            guard.bindExact(binding).requireStillActive()
            require(describeAdjustment(pending.row) != null) { "请回到原账本核对这次调整。" }
            require(drop || currentAccess()?.canModify == true) { "当前角色为只读，无法重试调整。" }
            require(drop || pending.hasSupportedIntent) { "当前版本无法读取原调整，请升级后继续。" }
            when (pending.row.status) {
                PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(pending.row.id, ConflictResolution.DropMine)
                PendingMutationStatus.Failed -> outbox.resolveFailed(pending.row.id,
                    if (drop) FailedResolution.Drop else FailedResolution.Retry())
                else -> Unit
            }
        }
}
