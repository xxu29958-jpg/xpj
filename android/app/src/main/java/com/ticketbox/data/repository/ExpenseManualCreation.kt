package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
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
            .mapLatest { rows -> findCreateByClientRef(rows, binding, ref) { core.describeManualCreation(it) } }
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
            .mapLatest { rows ->
                admission.withLock {
                    classifyExactOrigin(
                        rows,
                        binding,
                        origin,
                        core.offlineMutations.recurringPaymentCreateAdapter,
                    ) { core.describeManualCreation(it) }
                }
            }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observePeriodOrigin(
        binding: LogicalSessionBinding,
        seriesPublicId: String,
        period: String,
    ): Flow<RecurringPaymentPeriodOccupant> {
        if (seriesPublicId.isBlank() || period.isBlank()) {
            return flowOf(RecurringPaymentPeriodOccupant.Absent)
        }
        val requested = RecurringPaymentOrigin(seriesPublicId, period)
        return core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .mapLatest { rows ->
                admission.withLock {
                    classifyPeriodOccupant(
                        matchingPeriodOrigins(
                            rows,
                            binding,
                            requested,
                            core.offlineMutations.recurringPaymentCreateAdapter,
                        ) { core.describeManualCreation(it) },
                    )
                }
            }
    }

    suspend fun create(
        draft: ExpenseDraft,
        binding: LogicalSessionBinding,
        clientRef: String,
        origin: RecurringPaymentOrigin? = null,
        acknowledgedUnattributed: Collection<String> = emptyList(),
    ): Result<ManualExpenseCreateAdmission> = core.errorHandler.safeCall {
        admission.withLock {
            admitCreate(draft, binding, clientRef, origin, acknowledgedUnattributed)
        }
    }

    private suspend fun admitCreate(
        draft: ExpenseDraft,
        binding: LogicalSessionBinding,
        clientRef: String,
        origin: RecurringPaymentOrigin?,
        acknowledgedUnattributed: Collection<String>,
    ): ManualExpenseCreateAdmission {
        require(clientRef.isNotBlank())
        val bound = core.ledgerRequestGuard.bindExact(binding)
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        val rows = activeCreateRows()
        if (origin != null) {
            if (origin.occurrenceRowVersion == null) {
                return ManualExpenseCreateAdmission.Blocked(RecurringPaymentAdmissionBlock.MissingGeneration)
            }
            admittedExistingPeriod(
                classifyPeriodAdmission(
                    matchingPeriodOrigins(rows, binding, origin, originAdapter) { core.describeManualCreation(it) },
                    origin,
                ),
            )?.let {
                bound.requireStillActive()
                return it
            }
        }
        val existing = findCreateByClientRef(rows, binding, clientRef) { core.describeManualCreation(it) }
        if (existing != null) {
            if (origin != null) {
                tryBindOrigin(existing.row, origin).requireBoundOrRetired(
                    decodeRecurringPaymentPayload(originAdapter, existing.row.payloadJson),
                    origin,
                )
            }
            bound.requireStillActive()
            return ManualExpenseCreateAdmission.Accepted(clientRef)
        }
        if (origin != null) {
            val unattributed = unattributedCreations(rows, binding, originAdapter) { core.describeManualCreation(it) }
            val review = ManualExpenseCreateAdmission.ReviewRequired(unattributed)
            if (unattributed.isNotEmpty() && review.candidateClientRefs.toSet() != acknowledgedUnattributed.toSet()) {
                bound.requireStillActive()
                return review
            }
        }
        check(core.canModifyLedger()) { "当前账本没有编辑权限。" }
        require(draft.amountCents != null || draft.originalAmountMinor != null) { "请先填写金额。" }
        core.enqueueLocalCreate(
            bound, draft.copy(clientRef = clientRef), clientRef,
            encodeManualCreatePayload(
                core.offlineMutations.manualCreateAdapter, originAdapter,
                draft.toManualCreateRequest(clientRef = clientRef), origin,
            ),
        )
        bound.requireStillActive()
        return ManualExpenseCreateAdmission.Accepted(clientRef)
    }

    suspend fun retireOrigin(
        binding: LogicalSessionBinding,
        origin: RecurringPaymentOrigin,
        clientRef: String,
    ): RecurringPaymentOriginRetire {
        if (origin.seriesPublicId.isBlank() || origin.period.isBlank() || clientRef.isBlank()) {
            return RecurringPaymentOriginRetire.Missing
        }
        return admission.withLock {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            val projection = observe(binding, clientRef).first() ?: return@withLock RecurringPaymentOriginRetire.Missing
            val row = projection.row
            if (!row.isBoundCreate(binding, clientRef)) return@withLock RecurringPaymentOriginRetire.Missing
            val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
            val stored = decodeRecurringPaymentPayload(originAdapter, row.payloadJson)
                ?: return@withLock RecurringPaymentOriginRetire.Missing
            stored.originRetireDecision(origin, clientRef, row.status, projection.acceptedExpenseId)
                ?.let { return@withLock it }
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
            RecurringPaymentOriginRetire.Retired
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
        if (occurrenceRowVersion == null) {
            return@withLock RecurringPaymentOriginAdopt.Blocked(
                RecurringPaymentAdmissionBlock.MissingGeneration,
            )
        }
        val origin = RecurringPaymentOrigin(seriesPublicId, period, occurrenceRowVersion)
        val bound = core.ledgerRequestGuard.bindExact(binding)
        val rows = activeCreateRows()
        val originAdapter = core.offlineMutations.recurringPaymentCreateAdapter
        when (
            val state = classifyPeriodAdmission(
                matchingPeriodOrigins(rows, binding, origin, originAdapter) { core.describeManualCreation(it) },
                origin,
            )
        ) {
            PeriodOriginAdmission.Conflict -> RecurringPaymentOriginAdopt.Conflict
            is PeriodOriginAdmission.DifferentGeneration ->
                RecurringPaymentOriginAdopt.Blocked(
                    RecurringPaymentAdmissionBlock.DifferentGeneration,
                    periodOccupant(state.projection, state.occurrenceRowVersion),
                )
            is PeriodOriginAdmission.Exact ->
                if (state.projection.admittedClientRef() != clientRef) {
                    RecurringPaymentOriginAdopt.Conflict
                } else {
                    bound.requireStillActive()
                    RecurringPaymentOriginAdopt.Bound
                }
            PeriodOriginAdmission.Empty -> adoptUnwrappedOrigin(rows, binding, clientRef, origin, bound)
        }
    }

    private suspend fun adoptUnwrappedOrigin(
        rows: List<OutboxRow>,
        binding: LogicalSessionBinding,
        clientRef: String,
        origin: RecurringPaymentOrigin,
        bound: BoundLedgerRequest,
    ): RecurringPaymentOriginAdopt {
        val matches = rows.filter { row ->
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

    suspend fun readReviewCandidates(
        binding: LogicalSessionBinding,
    ): Result<List<ManualExpenseCreationProjection>> = core.errorHandler.safeCall {
        admission.withLock {
            val bound = core.ledgerRequestGuard.bindExact(binding)
            unattributedCreations(
                activeCreateRows(),
                binding,
                core.offlineMutations.recurringPaymentCreateAdapter,
            ) { core.describeManualCreation(it) }.also { bound.requireStillActive() }
        }
    }

    private suspend fun activeCreateRows(): List<OutboxRow> =
        core.offlineMutations.outbox
            .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
            .first()

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

internal suspend fun ExpenseManualCreation.inspectOrigin(
    binding: LogicalSessionBinding,
    origin: RecurringPaymentOrigin,
): RecurringPaymentOriginLookup = observeOrigin(binding, origin).first()

private suspend fun classifyExactOrigin(
    rows: List<OutboxRow>,
    binding: LogicalSessionBinding,
    origin: RecurringPaymentOrigin,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    describe: suspend (OutboxRow) -> ManualExpenseCreationProjection?,
): RecurringPaymentOriginLookup {
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
        describe(row)
    }
    return when (matches.size) {
        0 -> RecurringPaymentOriginLookup.Absent
        1 -> RecurringPaymentOriginLookup.Found(matches.single())
        else -> RecurringPaymentOriginLookup.Conflict
    }
}

private fun admittedExistingPeriod(
    state: PeriodOriginAdmission,
): ManualExpenseCreateAdmission? = when (state) {
    PeriodOriginAdmission.Conflict -> error("本期付款命令冲突，请先处理重复提交。")
    is PeriodOriginAdmission.DifferentGeneration ->
        ManualExpenseCreateAdmission.Blocked(
            RecurringPaymentAdmissionBlock.DifferentGeneration,
            periodOccupant(state.projection, state.occurrenceRowVersion),
        )
    is PeriodOriginAdmission.Exact ->
        ManualExpenseCreateAdmission.Accepted(
            state.projection.admittedClientRef() ?: error("本期付款命令冲突，请先处理重复提交。"),
        )
    PeriodOriginAdmission.Empty -> null
}

private suspend fun matchingPeriodOrigins(
    rows: List<OutboxRow>,
    binding: LogicalSessionBinding,
    requested: RecurringPaymentOrigin,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    describe: suspend (OutboxRow) -> ManualExpenseCreationProjection?,
): List<Pair<RecurringPaymentCreatePayload, ManualExpenseCreationProjection>> = rows.mapNotNull { row ->
    val boundRow = row.bindingOrNull() ?: return@mapNotNull null
    if (boundRow.serverUrl != binding.serverUrl ||
        boundRow.ledgerId != binding.ledgerId ||
        boundRow.owner?.storageKey != binding.ownerKey
    ) {
        return@mapNotNull null
    }
    val stored = decodeRecurringPaymentPayload(originAdapter, row.payloadJson) ?: return@mapNotNull null
    if (!stored.matchesOrigin(requested)) return@mapNotNull null
    val projection = describe(row) ?: return@mapNotNull null
    if (stored.isSafeRetired(projection.row.status, projection.acceptedExpenseId)) return@mapNotNull null
    stored to projection
}

private suspend fun findCreateByClientRef(
    rows: List<OutboxRow>,
    binding: LogicalSessionBinding,
    clientRef: String,
    describe: suspend (OutboxRow) -> ManualExpenseCreationProjection?,
): ManualExpenseCreationProjection? = rows.singleOrNull { row ->
    val boundRow = row.bindingOrNull()
    row.targetId == expenseLocalTargetId(clientRef) &&
        boundRow != null &&
        boundRow.serverUrl == binding.serverUrl &&
        boundRow.ledgerId == binding.ledgerId &&
        boundRow.owner?.storageKey == binding.ownerKey
}?.let { describe(it) }

private fun RecurringPaymentOriginAdopt.requireBoundOrRetired(
    stored: RecurringPaymentCreatePayload?,
    origin: RecurringPaymentOrigin,
) {
    when (this) {
        RecurringPaymentOriginAdopt.Bound -> Unit
        RecurringPaymentOriginAdopt.Conflict, is RecurringPaymentOriginAdopt.Blocked ->
            error("本期付款命令冲突，请先处理重复提交。")
        RecurringPaymentOriginAdopt.Missing ->
            if (stored?.retired != true || !stored.matchesOrigin(origin)) {
                error("原付款命令无法补上来源。")
            }
    }
}

private suspend fun unattributedCreations(
    rows: List<OutboxRow>,
    binding: LogicalSessionBinding,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    describe: suspend (OutboxRow) -> ManualExpenseCreationProjection?,
): List<ManualExpenseCreationProjection> = rows.mapNotNull { row ->
    val boundRow = row.bindingOrNull() ?: return@mapNotNull null
    if (boundRow.serverUrl != binding.serverUrl ||
        boundRow.ledgerId != binding.ledgerId ||
        boundRow.owner?.storageKey != binding.ownerKey
    ) {
        return@mapNotNull null
    }
    if (decodeRecurringPaymentPayload(originAdapter, row.payloadJson) != null) return@mapNotNull null
    describe(row)
}.sortedBy { it.admittedClientRef().orEmpty() }

private fun OutboxRow.isBoundCreate(binding: LogicalSessionBinding, clientRef: String): Boolean {
    val boundRow = bindingOrNull() ?: return false
    return boundRow.serverUrl == binding.serverUrl &&
        boundRow.ledgerId == binding.ledgerId &&
        boundRow.owner?.storageKey == binding.ownerKey &&
        targetId == expenseLocalTargetId(clientRef)
}

private fun RecurringPaymentCreatePayload.originRetireDecision(
    origin: RecurringPaymentOrigin,
    clientRef: String,
    status: PendingMutationStatus,
    acceptedExpenseId: Long?,
): RecurringPaymentOriginRetire? {
    if (!matchesOrigin(origin) || request.clientRef != clientRef) return RecurringPaymentOriginRetire.Missing
    if (occurrenceRowVersion != origin.occurrenceRowVersion) return RecurringPaymentOriginRetire.GenerationMismatch
    if (status != PendingMutationStatus.Done) return RecurringPaymentOriginRetire.CommandActive(status)
    if ((acceptedExpenseId ?: 0L) <= 0L) return RecurringPaymentOriginRetire.UnverifiedReceipt
    if (retired) return RecurringPaymentOriginRetire.Retired
    return null
}

private fun classifyPeriodOccupant(
    active: List<Pair<RecurringPaymentCreatePayload, ManualExpenseCreationProjection>>,
): RecurringPaymentPeriodOccupant {
    if (active.size > 1) return RecurringPaymentPeriodOccupant.Conflict
    val (stored, projection) = active.singleOrNull() ?: return RecurringPaymentPeriodOccupant.Absent
    return periodOccupant(projection, stored.occurrenceRowVersion) ?: RecurringPaymentPeriodOccupant.Conflict
}
