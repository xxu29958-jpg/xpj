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
                    val boundRow = row.bindingOrNull()
                    row.targetId == expenseLocalTargetId(ref) &&
                        boundRow != null &&
                        boundRow.serverUrl == binding.serverUrl &&
                        boundRow.ledgerId == binding.ledgerId &&
                        boundRow.owner?.storageKey == binding.ownerKey
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
    ): Result<ManualExpenseCreateAdmission> = core.errorHandler.safeCall {
        admission.withLock {
            require(clientRef.isNotBlank())
            val bound = core.ledgerRequestGuard.bindExact(binding)
            if (origin != null) {
                when (val found = classifyOrigin(activeCreateRows(), binding, origin)) {
                    RecurringPaymentOriginLookup.Conflict ->
                        error("本期付款命令冲突，请先处理重复提交。")
                    is RecurringPaymentOriginLookup.Found -> {
                        tryBindOrigin(found.projection.row, origin).requireBound()
                        bound.requireStillActive()
                        return@withLock ManualExpenseCreateAdmission.Accepted(
                            found.projection.admittedClientRef()
                                ?: error("本期付款命令冲突，请先处理重复提交。"),
                        )
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
            } else if (origin != null) {
                tryBindOrigin(existing.row, origin).requireBound()
            }
            bound.requireStillActive()
            ManualExpenseCreateAdmission.Accepted(clientRef)
        }
    }

    suspend fun retireOrigin(binding: LogicalSessionBinding, origin: RecurringPaymentOrigin) {
        if (origin.seriesPublicId.isBlank() || origin.period.isBlank()) return
        admission.withLock {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            val found = classifyOrigin(activeCreateRows(), binding, origin) as? RecurringPaymentOriginLookup.Found
                ?: return@withLock
            val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
            val request = decodeManualCreateRequest(
                core.offlineMutations.manualCreateAdapter,
                originAdapter,
                found.projection.row.payloadJson,
            ) ?: return@withLock
            core.offlineMutations.outbox.replaceCreateExpensePayload(
                found.projection.row.id,
                encodeManualCreatePayload(
                    core.offlineMutations.manualCreateAdapter,
                    originAdapter,
                    request,
                    origin = null,
                ),
            )
            bound.requireStillActive()
        }
    }

    suspend fun adoptOrigin(
        binding: LogicalSessionBinding,
        clientRef: String,
        seriesPublicId: String,
        period: String,
    ): RecurringPaymentOriginAdopt = admission.withLock {
        if (clientRef.isBlank() || seriesPublicId.isBlank() || period.isBlank()) {
            return@withLock RecurringPaymentOriginAdopt.Missing
        }
        val origin = RecurringPaymentOrigin(seriesPublicId, period)
        val bound = core.ledgerRequestGuard.bindExact(binding)
        when (val found = classifyOrigin(activeCreateRows(), binding, origin)) {
            RecurringPaymentOriginLookup.Conflict -> RecurringPaymentOriginAdopt.Conflict
            is RecurringPaymentOriginLookup.Found -> adoptFoundOrigin(found, clientRef, origin, bound)
            RecurringPaymentOriginLookup.Absent -> adoptUnwrappedOrigin(binding, clientRef, origin, bound)
        }
    }

    private suspend fun adoptFoundOrigin(
        found: RecurringPaymentOriginLookup.Found,
        clientRef: String,
        origin: RecurringPaymentOrigin,
        bound: BoundLedgerRequest,
    ): RecurringPaymentOriginAdopt {
        if (found.projection.admittedClientRef() != clientRef) return RecurringPaymentOriginAdopt.Conflict
        return tryBindOrigin(found.projection.row, origin).also { result ->
            if (result == RecurringPaymentOriginAdopt.Bound) bound.requireStillActive()
        }
    }

    private suspend fun adoptUnwrappedOrigin(
        binding: LogicalSessionBinding,
        clientRef: String,
        origin: RecurringPaymentOrigin,
        bound: BoundLedgerRequest,
    ): RecurringPaymentOriginAdopt {
        val matches = activeCreateRows().filter { row ->
            val boundRow = row.bindingOrNull()
            boundRow != null &&
                boundRow.serverUrl == binding.serverUrl &&
                boundRow.ledgerId == binding.ledgerId &&
                boundRow.owner?.storageKey == binding.ownerKey &&
                row.targetId == expenseLocalTargetId(clientRef)
        }
        val row = matches.singleOrNull() ?: return if (matches.isEmpty()) {
            RecurringPaymentOriginAdopt.Missing
        } else {
            RecurringPaymentOriginAdopt.Conflict
        }
        return tryBindOrigin(row, origin).also { result ->
            if (result == RecurringPaymentOriginAdopt.Bound) bound.requireStillActive()
        }
    }

    private suspend fun classifyOrigin(
        rows: List<OutboxRow>,
        binding: LogicalSessionBinding,
        origin: RecurringPaymentOrigin,
    ): RecurringPaymentOriginLookup {
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val matches = rows.mapNotNull { row ->
            val boundRow = row.bindingOrNull() ?: return@mapNotNull null
            if (boundRow.serverUrl != binding.serverUrl ||
                boundRow.ledgerId != binding.ledgerId ||
                boundRow.owner?.storageKey != binding.ownerKey
            ) {
                return@mapNotNull null
            }
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

    private suspend fun tryBindOrigin(row: OutboxRow, origin: RecurringPaymentOrigin): RecurringPaymentOriginAdopt {
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val current = decodeRecurringPaymentOrigin(originAdapter, row.payloadJson)
        if (current == origin) return RecurringPaymentOriginAdopt.Bound
        if (current != null) return RecurringPaymentOriginAdopt.Conflict
        val request = decodeManualCreateRequest(
            core.offlineMutations.manualCreateAdapter,
            originAdapter,
            row.payloadJson,
        ) ?: return RecurringPaymentOriginAdopt.Missing
        if (!core.offlineMutations.outbox.replaceCreateExpensePayload(
                row.id,
                encodeManualCreatePayload(
                    core.offlineMutations.manualCreateAdapter,
                    originAdapter,
                    request,
                    origin,
                ),
            )
        ) {
            return RecurringPaymentOriginAdopt.Missing
        }
        return RecurringPaymentOriginAdopt.Bound
    }
}

private fun RecurringPaymentOriginAdopt.requireBound() {
    when (this) {
        RecurringPaymentOriginAdopt.Bound -> Unit
        RecurringPaymentOriginAdopt.Conflict ->
            error("本期付款命令冲突，请先处理重复提交。")
        RecurringPaymentOriginAdopt.Missing ->
            error("原付款命令无法补上来源。")
    }
}
