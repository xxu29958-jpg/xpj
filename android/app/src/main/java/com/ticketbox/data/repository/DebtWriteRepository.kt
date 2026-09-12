package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import java.time.Clock
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

interface DebtWriteActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observeWrites(): Flow<DebtWriteObservation>
    fun observeWrites(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingDebtWrite>>
    fun describeWrite(row: OutboxRow): PendingDebtWrite?
    suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long>
    suspend fun saveRepayment(binding: LogicalSessionBinding, debt: Debt, amountCents: Long): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtWrite, drop: Boolean): Result<Unit>
}

/** Publishes either original debt command; the matching thin dispatcher owns network delivery. */
class DebtWriteRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val adapter: JsonAdapter<DebtAdjustmentPayload>,
    private val repaymentAdapter: JsonAdapter<DebtRepaymentPayload>,
    private val clock: Clock = Clock.systemUTC(),
) : DebtWriteActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Debt write")

    override fun currentAccess(): LedgerAccessContext? = guard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, ledgerRoleCanModify(apiProvider.currentLedgerRole()))
    }

    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeWrites(): Flow<DebtWriteObservation> = observeActiveLedgerAccess()
        .map { it?.binding }.distinctUntilChanged().flatMapLatest { binding ->
            if (binding == null) flowOf(DebtWriteObservation(null, emptyList(), true, emptyList()))
            else flow {
                var initial = true
                val seen = mutableSetOf<Long>()
                outbox.observeDebtWrites()
                    .collect { rows ->
                        if (guard.captureLogicalBinding() != binding) return@collect
                        val descriptions = rows.mapNotNull(::describeWrite)
                        val terminal = descriptions.filter { it.isTerminal }
                        val arrived = if (initial) emptyList() else terminal.filter { it.row.id !in seen }
                        seen += terminal.map { it.row.id }
                        emit(DebtWriteObservation(binding, descriptions, initial, arrived))
                        initial = false
                    }
            }
        }

    override fun describeWrite(row: OutboxRow): PendingDebtWrite? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type !in DEBT_WRITE_TYPES ||
            row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId
        ) return null
        return when (row.type) {
            PendingMutationType.RecordDebtAdjustment -> row.describeDebtAdjustment(adapter)
            PendingMutationType.RecordDebtRepayment -> row.describeDebtRepayment(repaymentAdapter)
            else -> null
        }
    }

    override fun observeWrites(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingDebtWrite>> =
        outbox.observeDebtWrites().map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList()
            else rows.filter { it.targetId == debtWriteTarget(publicId) }.mapNotNull(::describeWrite)
        }

    override suspend fun save(binding: LogicalSessionBinding, debt: Debt, amountCents: Long, reason: String): Result<Long> =
        errors.safeCall {
            val cleanReason = trimDebtAdjustmentReason(reason)
            require(amountCents != 0L && cleanReason.isNotEmpty() && debt.rowVersion > 0L) { "请填写调整金额和原因。" }
            require(isDebtAdjustmentReasonValid(cleanReason)) { "调整原因不能超过 500 个字符。" }
            require(isDebtAdjustmentWithinBalance(amountCents, debt.remainingAmountCents)) { "减少金额不能超过当前剩余金额。" }
            val payload = DebtAdjustmentPayload(
                revision = 1,
                subject = DebtWriteSubject(debt.publicId, debt.counterpartyLabel, debt.homeCurrencyCode),
                originSessionGeneration = binding.sessionGeneration,
                originBindingRevision = binding.bindingRevision,
                request = DebtAdjustmentCreateRequestDto(amountCents, cleanReason, debt.rowVersion),
            )
            publish(binding, debt, type = PendingMutationType.RecordDebtAdjustment, payload = adapter.toJson(payload))
        }

    override suspend fun saveRepayment(binding: LogicalSessionBinding, debt: Debt, amountCents: Long): Result<Long> =
        errors.safeCall {
            require(amountCents > 0L && amountCents <= debt.remainingAmountCents) { "还款金额必须大于零且不超过当前剩余金额。" }
            val payload = DebtRepaymentPayload(1, DebtWriteSubject(debt.publicId, debt.counterpartyLabel, debt.homeCurrencyCode),
                binding.sessionGeneration, binding.bindingRevision,
                RepaymentCreateRequestDto(amountCents, debt.rowVersion, clock.instant().toString()))
            publish(binding, debt, type = PendingMutationType.RecordDebtRepayment, payload = repaymentAdapter.toJson(payload))
        }

    private suspend fun publish(binding: LogicalSessionBinding, debt: Debt, type: PendingMutationType, payload: String): Long {
        val bound = guard.bindExact(binding)
        require(currentAccess()?.canModify == true) { "当前角色为只读，无法修改账本。" }
        require(debt.ledgerId == binding.ledgerId && debt.isDirectWritable && !debt.isVoided && debt.rowVersion > 0L) {
            "这笔欠款不能直接修改。"
        }
        require(CurrencyCode.fromStorageKeyOrNull(debt.homeCurrencyCode) != null) { "当前版本不支持这笔欠款的币种。" }
        return outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(type = type,
            targetId = debtWriteTarget(debt.publicId), payloadJson = payload, expectedRowVersion = debt.rowVersion,
            idempotencyKey = UUID.randomUUID().toString()), validateTargetRows = { rows ->
                if (rows.any { it.status != PendingMutationStatus.Done }) {
                    throw RepositoryException("这笔欠款还有待处理的还款或调整，请先核对原提交。")
                }
            })
    }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingDebtWrite, drop: Boolean): Result<Unit> =
        errors.safeCall {
            val bound = guard.bindExact(binding)
            bound.requireStillActive()
            val current = outbox.activeForTarget(bound, pending.row.targetId).firstOrNull { it.id == pending.row.id }
                ?: throw RepositoryException("这次本地提交状态已变化，请重新核对。")
            val original = describeWrite(current)
            require(original != null) { "请回到原账本核对这次提交。" }
            require(drop || currentAccess()?.canModify == true) { "当前角色为只读，无法重试提交。" }
            require(drop || original.hasSupportedIntent) { "当前版本无法读取原提交，请升级后继续。" }
            require(drop || original.canRetry) { "这次原提交不能重试，请核对后处理本地记录。" }
            val changed = if (drop) outbox.abandonDebtWrite(bound, current)
                else outbox.resolveFailed(current.id, FailedResolution.Retry())
            if (!changed) throw RepositoryException("这次本地提交状态已变化，请重新核对。")
        }
}
