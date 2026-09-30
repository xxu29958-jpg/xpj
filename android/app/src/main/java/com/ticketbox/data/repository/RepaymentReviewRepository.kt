package com.ticketbox.data.repository

import androidx.room.withTransaction
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.RepaymentReviewInputEntity
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.math.BigDecimal
import java.util.UUID
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

data class RepaymentReviewState(val input: RepaymentReviewInputEntity?, val original: OutboxRow? = null,
    val bindingChanged: Boolean = false) {
    val canRetry: Boolean get() = original?.status == PendingMutationStatus.Failed && !bindingChanged &&
        original.lastError?.startsWith("outbox_row_expired") != true
    val canStop: Boolean get() = original?.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) ||
        original?.status == PendingMutationStatus.Pending && bindingChanged
}

interface RepaymentReviewActions {
    fun observe(binding: LogicalSessionBinding, draftId: String): Flow<RepaymentReviewState>
    suspend fun open(binding: LogicalSessionBinding, draft: RepaymentDraft, suggested: Debt? = null): Result<Unit>
    suspend fun money(binding: LogicalSessionBinding, draftId: String, currency: String, amount: String): Result<Unit>
    suspend fun select(binding: LogicalSessionBinding, draftId: String, debt: Debt): Result<Unit>
    suspend fun submit(binding: LogicalSessionBinding, draft: RepaymentDraft, dismiss: Boolean): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, draftId: String, stop: Boolean): Result<Unit>
    suspend fun recoverOriginal(binding: LogicalSessionBinding, row: OutboxRow, stop: Boolean): Result<Unit>
    suspend fun reviewAgain(binding: LogicalSessionBinding, draftId: String): Result<Unit>
}

/** One input owner; acceptance atomically freezes that input beside its existing Outbox command. */
class RepaymentReviewRepository internal constructor(
    private val provider: ApiServiceProvider,
    private val database: AppDatabase,
    private val outbox: OutboxRepository,
    private val adapters: OutboxAdapterGraph,
) : RepaymentReviewActions {
    private val guard = LedgerRequestGuard(provider)
    private val inputs = database.repaymentReviewInputDao()
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Repayment review")

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observe(binding: LogicalSessionBinding, draftId: String): Flow<RepaymentReviewState> =
        inputs.observe(binding.ownerKey, binding.ledgerId, draftId).flatMapLatest { input ->
            val action = input?.submittedAction
            val changed = input?.matches(binding) == false
            if (action == null) flowOf(RepaymentReviewState(input, bindingChanged = changed))
            else outbox.observeOriginalCommand(PendingMutationType.fromWire(action), input.originalKey)
                .map { RepaymentReviewState(input, it.singleOrNull(), changed) }
        }

    override suspend fun open(binding: LogicalSessionBinding, draft: RepaymentDraft, suggested: Debt?): Result<Unit> = errors.safeCall {
        outbox.withActiveBinding(guard.bindExact(binding)) {
            database.withTransaction {
                if (inputs.get(binding.ownerKey, binding.ledgerId, draft.publicId) != null) return@withTransaction
                if (!draft.isPending) return@withTransaction
                val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(draft.originalCurrencyCode))
                val input = RepaymentReviewInputEntity(binding.ownerKey, binding.ledgerId, draft.publicId,
                    binding.serverUrl, binding.sessionGeneration, binding.bindingRevision, UUID.randomUUID().toString(),
                    currency.storageKey, BigDecimal.valueOf(draft.originalAmountMinor, currency.minorUnitDigits).toPlainString())
                inputs.put(if (suggested == null) input else input.selectDebt(binding, suggested))
            }
        }
    }

    override suspend fun money(binding: LogicalSessionBinding, draftId: String, currency: String, amount: String): Result<Unit> =
        edit(binding, draftId) { it.copy(currency = currency, amountText = amount) }

    override suspend fun select(binding: LogicalSessionBinding, draftId: String, debt: Debt): Result<Unit> =
        edit(binding, draftId) { it.selectDebt(binding, debt) }

    private suspend fun edit(binding: LogicalSessionBinding, draftId: String,
        transform: (RepaymentReviewInputEntity) -> RepaymentReviewInputEntity): Result<Unit> = errors.safeCall {
        outbox.withActiveBinding(guard.bindExact(binding)) {
            database.withTransaction {
                val input = requireInput(binding, draftId)
                require(input.submittedAction == null) { "原提交已保存；请先核对结果，不能改写正在处理的内容。" }
                inputs.put(transform(input))
            }
        }
    }

    override suspend fun submit(binding: LogicalSessionBinding, draft: RepaymentDraft, dismiss: Boolean): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(binding)
        require(ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色为只读，无法修改账本。" }
        val input = requireInput(binding, draft.publicId)
        if (input.submittedAction != null) return@safeCall requireNotNull(observe(binding, draft.publicId).first().original) {
            "原提交已保存，请刷新核对原处理结果。"
        }.id
        require(draft.isPending) { "这条采集已处理，请查看原结果。" }
        val command = input.command(binding, draft, dismiss, adapters)
        outbox.enqueue(bound, command, validateTargetRows = { rows ->
            require(rows.none { it.status != PendingMutationStatus.Done }) { "这笔欠款还有待处理的提交，请先核对原提交。" }
        }, afterPersisted = {
            // This callback shares the Outbox insert's Room transaction and binding lease.
            require(requireInput(binding, draft.publicId) == input) { "核对内容已变化，请重新确认。" }
            inputs.put(input.copy(submittedAction = command.type.wireValue))
        })
    }

    override suspend fun recover(binding: LogicalSessionBinding, draftId: String, stop: Boolean): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val state = observe(binding, draftId).first()
        val row = requireNotNull(state.original) { "请先读取原提交。" }
        val input = requireNotNull(state.input)
        val canStop = row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) ||
            row.status == PendingMutationStatus.Pending && !input.matches(binding)
        require(if (stop) canStop else row.status == PendingMutationStatus.Failed && input.matches(binding) &&
            ledgerRoleCanModify(provider.currentLedgerRole())) { "原提交状态已变化，请重新核对。" }
        val changed = if (stop) outbox.abandonOriginalCommand(bound, row)
            else outbox.resolveFailed(row.id, FailedResolution.Retry(), bound)
        require(changed) { "原提交状态已变化，请重新核对。" }
    }

    override suspend fun recoverOriginal(binding: LogicalSessionBinding, row: OutboxRow, stop: Boolean): Result<Unit> = errors.safeCall {
        guard.bindExact(binding)
        require(row.type == PendingMutationType.DismissRepaymentDraft && row.targetId.startsWith("repayment-draft:"))
        val draftId = row.targetId.removePrefix("repayment-draft:")
        require(observe(binding, draftId).first().original?.id == row.id) { "请打开原采集核对这次提交。" }
        recover(binding, draftId, stop).getOrThrow()
    }

    override suspend fun reviewAgain(binding: LogicalSessionBinding, draftId: String): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val old = observe(binding, draftId).first()
        require(ledgerRoleCanModify(provider.currentLedgerRole())) { "当前角色为只读，无法修改账本。" }
        val unsubmittedOldBinding = old.input?.submittedAction == null && old.bindingChanged
        require(old.original?.status == PendingMutationStatus.Abandoned || unsubmittedOldBinding) { "请先停止原提交的本机追踪。" }
        val current = bound.call { it.repaymentDraft(draftId) }
        require(current.status == "pending") { "这条采集已处理，请刷新查看原结果。" }
        outbox.withActiveBinding(bound) {
            database.withTransaction {
                val retained = requireNotNull(inputs.get(binding.ownerKey, binding.ledgerId, draftId))
                require(retained == old.input)
                inputs.put(retained.copy(originalKey = UUID.randomUUID().toString(), submittedAction = null,
                    serverUrl = binding.serverUrl,
                    sessionGeneration = binding.sessionGeneration, bindingRevision = binding.bindingRevision,
                    debtPublicId = null, debtLabel = null, debtHomeCurrency = null, debtRowVersion = null))
            }
        }
    }

    private suspend fun requireInput(binding: LogicalSessionBinding, draftId: String): RepaymentReviewInputEntity {
        val input = requireNotNull(inputs.get(binding.ownerKey, binding.ledgerId, draftId)) { "请先打开原采集核对。" }
        require(input.matches(binding)) { "连接身份已变化，原输入仍保留，请回到原身份处理。" }
        return input
    }
}

internal fun RepaymentReviewInputEntity.matches(binding: LogicalSessionBinding): Boolean =
    ownerKey == binding.ownerKey && ledgerId == binding.ledgerId && serverUrl == binding.serverUrl &&
        sessionGeneration == binding.sessionGeneration && bindingRevision == binding.bindingRevision

private fun RepaymentReviewInputEntity.selectDebt(binding: LogicalSessionBinding, debt: Debt): RepaymentReviewInputEntity {
    require(debt.ledgerId == binding.ledgerId && debt.isOpen && debt.isDirectWritable && debt.rowVersion > 0) {
        "请选择当前账本中可直接偿还的欠款。"
    }
    return copy(debtPublicId = debt.publicId, debtLabel = debt.counterpartyLabel,
        debtHomeCurrency = debt.homeCurrencyCode, debtRowVersion = debt.rowVersion)
}
