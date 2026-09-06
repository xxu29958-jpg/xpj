package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

interface DebtAdjustmentActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observeCompletionRefreshes(): Flow<DebtAdjustmentRefresh>
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

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeCompletionRefreshes(): Flow<DebtAdjustmentRefresh> = observeActiveLedgerAccess()
        .map { it?.binding }.distinctUntilChanged().flatMapLatest { binding ->
            if (binding == null) flowOf(DebtAdjustmentRefresh(null, initial = true))
            else flow {
                var initial = true
                val seen = mutableSetOf<Long>()
                outbox.observeActiveByTypes(setOf(PendingMutationType.RecordDebtAdjustment), includeCompleted = true)
                    .collect { rows ->
                        if (guard.captureLogicalBinding() != binding) return@collect
                        val completed = rows.filter { it.status == PendingMutationStatus.Done }.map { it.id }
                        val newlyCompleted = completed.any { it !in seen }
                        seen += completed
                        if (initial || newlyCompleted) {
                            emit(DebtAdjustmentRefresh(binding, initial))
                            initial = false
                        }
                    }
            }
        }

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
            val cleanReason = trimDebtAdjustmentReason(reason)
            require(amountCents != 0L && cleanReason.isNotEmpty() && debt.rowVersion > 0L) { "请填写调整金额和原因。" }
            require(isDebtAdjustmentReasonValid(cleanReason)) { "调整原因不能超过 500 个字符。" }
            require(isDebtAdjustmentWithinBalance(amountCents, debt.remainingAmountCents)) { "减少金额不能超过当前剩余金额。" }
            if (outbox.activeForTarget(bound, debtAdjustmentTarget(debt.publicId)).isNotEmpty()) {
                throw RepositoryException("这笔欠款还有待处理的调整，请先核对原提交。")
            }
            val payload = DebtAdjustmentPayload(
                revision = 1,
                subject = DebtAdjustmentSubject(debt.publicId, debt.counterpartyLabel, debt.homeCurrencyCode),
                originSessionGeneration = binding.sessionGeneration,
                originBindingRevision = binding.bindingRevision,
                request = DebtAdjustmentCreateRequestDto(amountCents, cleanReason, debt.rowVersion),
            )
            outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
                type = PendingMutationType.RecordDebtAdjustment, targetId = debtAdjustmentTarget(debt.publicId),
                payloadJson = adapter.toJson(payload), expectedRowVersion = debt.rowVersion,
                idempotencyKey = UUID.randomUUID().toString(),
            ))
        }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtAdjustment, drop: Boolean): Result<Unit> =
        errors.safeCall {
            val bound = guard.bindExact(binding)
            bound.requireStillActive()
            val current = outbox.activeForTarget(bound, pending.row.targetId).firstOrNull { it.id == pending.row.id }
                ?: throw RepositoryException("这次本地调整状态已变化，请重新核对。")
            val original = describeAdjustment(current)
            require(original != null) { "请回到原账本核对这次调整。" }
            require(drop || currentAccess()?.canModify == true) { "当前角色为只读，无法重试调整。" }
            require(drop || original.hasSupportedIntent) { "当前版本无法读取原调整，请升级后继续。" }
            require(drop || original.canRetry) { "这次原调整不能重试，请核对后处理本地记录。" }
            when (current.status) {
                PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(current.id, ConflictResolution.DropMine)
                PendingMutationStatus.Failed -> {
                    val changed = outbox.resolveFailed(current.id,
                        if (drop) FailedResolution.Drop else FailedResolution.Retry())
                    if (!drop && changed && outbox.activeForTarget(bound, current.targetId).any {
                            it.id == current.id && it.status == PendingMutationStatus.Pending
                        }) outbox.schedulePending()
                }
                else -> throw RepositoryException("这次本地调整状态已变化，请重新核对。")
            }
        }
}
