package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalUpdate
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map

internal class FakeCreateGoalEdits(
    canModify: Boolean = true,
    private val createResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
) : GoalEditActions {
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(adjustmentBinding(), canModify))
    val rows = MutableStateFlow<List<PendingGoalCreation>>(emptyList())
    val origins = mutableMapOf<Long, LogicalSessionBinding>()
    val createDebtGoalCalls = mutableListOf<CreateDebtGoalCall>()
    val createDebtGoalBindings = mutableListOf<LogicalSessionBinding>()
    val keys = mutableListOf<String>()
    var lookupFailure: Throwable? = null
    var lookupGate: (suspend () -> Unit)? = null
    var afterPersist: (suspend () -> Unit)? = null
    var persistBeforeFailure = false

    override fun currentAccess() = access.value
    override fun observeAccess() = access
    override fun observeCreations(binding: LogicalSessionBinding, originalKey: String?, goalType: String, originalId: Long?) =
        flow {
            lookupGate?.invoke()
            lookupFailure?.let { throw it }
            emitAll(rows.map { pending -> pending.filter {
                origins[it.row.id] == binding && (originalId == null || it.row.id == originalId) &&
                    (originalKey == null || it.row.idempotencyKey == originalKey) &&
                    (originalKey != null || originalId != null || it.request?.goalType == goalType)
            } })
        }

    override suspend fun create(binding: LogicalSessionBinding, request: GoalCreateRequestDto, creationKey: String): Result<Long> {
        createDebtGoalCalls += CreateDebtGoalCall(request.name, request.debtPublicIds.orEmpty())
        createDebtGoalBindings += binding
        keys += creationKey
        if (createResult.isFailure && !persistBeforeFailure) return Result.failure(requireNotNull(createResult.exceptionOrNull()))
        val id = (origins.keys.maxOrNull() ?: 0L) + 1
        val receipt = createResult.getOrNull()
        val row = debtCreationRow(binding, creationKey, id, if (receipt == null) PendingMutationStatus.Pending else PendingMutationStatus.Done)
        origins[id] = binding
        rows.value += PendingGoalCreation(row, request, receipt)
        afterPersist?.invoke()
        return if (createResult.isSuccess) Result.success(id) else Result.failure(requireNotNull(createResult.exceptionOrNull()))
    }

    override fun describeCreation(row: OutboxRow) = rows.value.firstOrNull { it.row.id == row.id }
    override suspend fun recoverCreation(binding: LogicalSessionBinding, pending: PendingGoalCreation, drop: Boolean): Result<Unit> {
        rows.value = rows.value.map { if (it.row.id == pending.row.id) it.copy(row = it.row.copy(
            status = if (drop) PendingMutationStatus.Abandoned else PendingMutationStatus.Pending)) else it }
        return Result.success(Unit)
    }
    override fun describeEdit(row: OutboxRow): PendingGoalEdit? = null
    override suspend fun currency(binding: LogicalSessionBinding) = Result.success(CurrencyCode.CNY)
    override fun observeEdits(binding: LogicalSessionBinding, publicId: String) = MutableStateFlow(emptyList<PendingGoalEdit>())
    override suspend fun save(binding: LogicalSessionBinding, goal: Goal, update: com.ticketbox.domain.model.GoalEditInput): Result<Long> = error("unused")
    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingGoalEdit, drop: Boolean): Result<Unit> = error("unused")
}

internal fun debtCreationRow(binding: LogicalSessionBinding, key: String, id: Long = 1,
    status: PendingMutationStatus = PendingMutationStatus.Pending) = OutboxRow(
    id, binding.serverUrl, binding.ledgerId, binding.ownerKey, PendingMutationType.CreateGoal,
    "goal_create:$key", "{}", 0, status, 0, null, "2026-09-28", null, null, key,
)

internal fun debtCreationGoal(publicId: String) = spendingGoal(publicId = publicId, goalType = "debt_repayment").copy(
    month = "", category = null, targetAmountCents = null, spentAmountCents = null,
    remainingAmountCents = null, progressPercent = null, homeCurrencyCode = null,
)
