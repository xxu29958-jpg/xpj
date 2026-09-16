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
        acknowledgedUnattributed: Collection<String> = emptyList(),
    ): Result<ManualExpenseCreateAdmission> = core.errorHandler.safeCall {
        admission.withLock {
            require(clientRef.isNotBlank())
            val bound = core.ledgerRequestGuard.bindExact(binding)
            val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
            if (origin != null) {
                when (val found = classifyOrigin(activeCreateRows(), binding, origin)) {
                    RecurringPaymentOriginLookup.Conflict ->
                        error("本期付款命令冲突，请先处理重复提交。")
                    is RecurringPaymentOriginLookup.Found -> {
                        tryBindOrigin(found.projection.row, origin).requireBoundOrRetired(
                            decodeRecurringPaymentPayload(originAdapter, found.projection.row.payloadJson),
                            origin,
                        )
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
            if (existing != null) {
                if (origin != null) {
                    tryBindOrigin(existing.row, origin).requireBoundOrRetired(
                        decodeRecurringPaymentPayload(originAdapter, existing.row.payloadJson),
                        origin,
                    )
                }
                bound.requireStillActive()
                return@withLock ManualExpenseCreateAdmission.Accepted(clientRef)
            }
            if (origin != null) {
                val unattributed = unattributedCreations(binding)
                val review = ManualExpenseCreateAdmission.ReviewRequired(unattributed)
                if (unattributed.isNotEmpty() && review.candidateClientRefs.toSet() != acknowledgedUnattributed.toSet()) {
                    bound.requireStillActive()
                    return@withLock review
                }
            }
            check(core.canModifyLedger()) { "当前账本没有编辑权限。" }
            require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
            val request = draft.toManualCreateRequest(clientRef = clientRef)
            core.enqueueLocalCreate(
                bound,
                draft.copy(clientRef = clientRef),
                clientRef,
                encodeManualCreatePayload(
                    core.offlineMutations.manualCreateAdapter,
                    originAdapter,
                    request,
                    origin,
                ),
            )
            bound.requireStillActive()
            ManualExpenseCreateAdmission.Accepted(clientRef)
        }
    }

    suspend fun retireOrigin(
        binding: LogicalSessionBinding,
        origin: RecurringPaymentOrigin,
        clientRef: String,
    ) {
        if (origin.seriesPublicId.isBlank() || origin.period.isBlank() || clientRef.isBlank()) return
        admission.withLock {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            val row = observe(binding, clientRef).first()?.row ?: return@withLock
            val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
            val stored = decodeRecurringPaymentPayload(originAdapter, row.payloadJson) ?: return@withLock
            if (stored.retired || !stored.matchesOrigin(origin)) return@withLock
            core.offlineMutations.outbox.replaceCreateExpensePayload(
                row.id,
                encodeManualCreatePayload(
                    core.offlineMutations.manualCreateAdapter,
                    originAdapter,
                    stored.request,
                    RecurringPaymentOrigin(stored.seriesPublicId, stored.period, stored.occurrenceRowVersion),
                    retired = true,
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
        occurrenceRowVersion: Long? = null,
    ): RecurringPaymentOriginAdopt = admission.withLock {
        if (clientRef.isBlank() || seriesPublicId.isBlank() || period.isBlank()) {
            return@withLock RecurringPaymentOriginAdopt.Missing
        }
        val origin = RecurringPaymentOrigin(seriesPublicId, period, occurrenceRowVersion)
        val bound = core.ledgerRequestGuard.bindExact(binding)
        when (val found = classifyOrigin(activeCreateRows(), binding, origin)) {
            RecurringPaymentOriginLookup.Conflict -> RecurringPaymentOriginAdopt.Conflict
            is RecurringPaymentOriginLookup.Found -> {
                if (found.projection.admittedClientRef() != clientRef) {
                    RecurringPaymentOriginAdopt.Conflict
                } else {
                    tryBindOrigin(found.projection.row, origin).also { result ->
                        if (result == RecurringPaymentOriginAdopt.Bound) bound.requireStillActive()
                    }
                }
            }
            RecurringPaymentOriginLookup.Absent -> adoptUnwrappedOrigin(binding, clientRef, origin, bound)
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
            if (decodeRecurringPaymentPayload(originAdapter, row.payloadJson)?.matchesActiveOrigin(origin) != true) {
                return@mapNotNull null
            }
            core.describeManualCreation(row)
        }
        return when (matches.size) {
            0 -> RecurringPaymentOriginLookup.Absent
            1 -> RecurringPaymentOriginLookup.Found(matches.single())
            else -> RecurringPaymentOriginLookup.Conflict
        }
    }

    suspend fun readReviewCandidates(
        binding: LogicalSessionBinding,
    ): Result<List<ManualExpenseCreationProjection>> = core.errorHandler.safeCall {
        admission.withLock {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            unattributedCreations(binding).also { bound.requireStillActive() }
        }
    }

    private suspend fun activeCreateRows(): List<OutboxRow> =
        core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .first()

    private suspend fun unattributedCreations(binding: LogicalSessionBinding): List<ManualExpenseCreationProjection> {
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        return activeCreateRows().mapNotNull { row ->
            val boundRow = row.bindingOrNull() ?: return@mapNotNull null
            if (boundRow.serverUrl != binding.serverUrl ||
                boundRow.ledgerId != binding.ledgerId ||
                boundRow.owner?.storageKey != binding.ownerKey
            ) {
                return@mapNotNull null
            }
            if (decodeRecurringPaymentPayload(originAdapter, row.payloadJson) != null) return@mapNotNull null
            core.describeManualCreation(row)
        }.sortedBy { it.admittedClientRef().orEmpty() }
    }

    private suspend fun tryBindOrigin(row: OutboxRow, origin: RecurringPaymentOrigin): RecurringPaymentOriginAdopt {
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val stored = decodeRecurringPaymentPayload(originAdapter, row.payloadJson)
        if (stored != null) {
            if (stored.retired) return RecurringPaymentOriginAdopt.Missing
            if (!stored.matchesOrigin(origin)) return RecurringPaymentOriginAdopt.Conflict
            if (stored.occurrenceRowVersion == origin.occurrenceRowVersion) {
                return RecurringPaymentOriginAdopt.Bound
            }
            if (stored.occurrenceRowVersion != null) return RecurringPaymentOriginAdopt.Missing
        }
        val request = stored?.request ?: decodeManualCreateRequest(
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

private fun RecurringPaymentOriginAdopt.requireBoundOrRetired(
    stored: RecurringPaymentCreatePayload?,
    origin: RecurringPaymentOrigin,
) {
    when (this) {
        RecurringPaymentOriginAdopt.Bound -> Unit
        RecurringPaymentOriginAdopt.Conflict ->
            error("本期付款命令冲突，请先处理重复提交。")
        RecurringPaymentOriginAdopt.Missing ->
            if (stored?.retired != true || !stored.matchesOrigin(origin)) {
                error("原付款命令无法补上来源。")
            }
    }
}
