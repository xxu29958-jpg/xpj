package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Manual entry admission. Commands still use the existing atomic Room/Outbox create. */
internal class ExpenseManualCreation(private val core: ExpenseRepositoryCore) {
    private val admission = Mutex()

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observe(binding: LogicalSessionBinding, clientRef: String): Flow<ManualExpenseCreationProjection?> {
        val ref = clientRef.takeIf(String::isNotBlank) ?: return flowOf(null)
        return core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .mapLatest { rows ->
                rows.singleOrNull { row ->
                    row.targetId == expenseLocalTargetId(ref) && row.belongsTo(binding)
                }?.let { core.describeManualCreation(it) }
            }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeOrigin(
        binding: LogicalSessionBinding,
        origin: RecurringPaymentOrigin,
    ): Flow<RecurringPaymentOriginLookup> {
        if (origin.seriesPublicId.isBlank() || origin.period.isBlank()) {
            return flowOf(RecurringPaymentOriginLookup.Absent)
        }
        return core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .mapLatest { rows -> classifyOrigin(rows, binding, origin) }
    }

    suspend fun create(
        draft: ExpenseDraft,
        binding: LogicalSessionBinding,
        clientRef: String,
        origin: RecurringPaymentOrigin? = null,
    ): Result<Unit> = core.errorHandler.safeCall {
        admission.withLock {
            require(clientRef.isNotBlank())
            val bound = core.ledgerRequestGuard.bindExact(binding)
            if (origin != null) {
                when (val found = classifyOrigin(activeCreateRows(), binding, origin)) {
                    RecurringPaymentOriginLookup.Conflict ->
                        error("本期付款命令冲突，请先处理重复提交。")
                    is RecurringPaymentOriginLookup.Found -> {
                        bindOrigin(found.projection.row, origin)
                        bound.requireStillActive()
                        return@withLock
                    }
                    RecurringPaymentOriginLookup.Absent -> Unit
                }
            }
            val existing = observe(binding, clientRef).first()
            if (existing == null) {
                check(core.canModifyLedger()) { "当前账本没有编辑权限。" }
                require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
                val request = draft.toManualCreateRequest(clientRef = clientRef)
                core.enqueueLocalCreate(
                    bound,
                    draft.copy(clientRef = clientRef),
                    clientRef,
                    encodeManualCreatePayload(
                        core.offlineMutations.manualCreateAdapter,
                        core.offlineMutations.recurringPaymentCreateAdapter,
                        request,
                        origin,
                    ),
                )
            } else {
                bindOrigin(existing.row, origin)
            }
            bound.requireStillActive()
        }
    }

    private suspend fun classifyOrigin(
        rows: List<OutboxRow>,
        binding: LogicalSessionBinding,
        origin: RecurringPaymentOrigin,
    ): RecurringPaymentOriginLookup {
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val matches = rows.mapNotNull { row ->
            if (!row.belongsTo(binding)) return@mapNotNull null
            if (decodeRecurringPaymentOrigin(originAdapter, row.payloadJson) != origin) return@mapNotNull null
            core.describeManualCreation(row)
        }
        return when (matches.size) {
            0 -> RecurringPaymentOriginLookup.Absent
            1 -> RecurringPaymentOriginLookup.Found(matches.single())
            else -> RecurringPaymentOriginLookup.Conflict
        }
    }

    private suspend fun activeCreateRows(): List<OutboxRow> =
        core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .first()

    private suspend fun bindOrigin(row: OutboxRow, origin: RecurringPaymentOrigin?) {
        if (origin == null) return
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val current = decodeRecurringPaymentOrigin(originAdapter, row.payloadJson)
        if (current == origin) return
        check(current == null) { "本期付款命令冲突，请先处理重复提交。" }
        val request = decodeManualCreateRequest(
            core.offlineMutations.manualCreateAdapter,
            originAdapter,
            row.payloadJson,
        ) ?: return
        check(
            core.offlineMutations.outbox.replaceCreateExpensePayload(
                row.id,
                encodeManualCreatePayload(
                    core.offlineMutations.manualCreateAdapter,
                    originAdapter,
                    request,
                    origin,
                ),
            ),
        ) { "原付款命令无法补上来源。" }
    }
}

private fun OutboxRow.belongsTo(binding: LogicalSessionBinding): Boolean {
    val row = bindingOrNull() ?: return false
    return row.serverUrl == binding.serverUrl &&
        row.ledgerId == binding.ledgerId &&
        row.owner?.storageKey == binding.ownerKey
}
