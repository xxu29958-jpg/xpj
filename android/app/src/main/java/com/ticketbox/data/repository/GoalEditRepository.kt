package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

interface GoalEditActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    suspend fun currency(binding: LogicalSessionBinding): Result<CurrencyCode>
    fun observeEdits(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingGoalEdit>>
    suspend fun save(binding: LogicalSessionBinding, goal: Goal, update: GoalUpdate): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, pending: PendingGoalEdit, drop: Boolean): Result<Unit>
}

data class PendingGoalEdit(val row: OutboxRow, val request: GoalUpdateRequestDto?, val confirmed: Goal?) {
    val isDone: Boolean get() = row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = request != null && row.status == PendingMutationStatus.Failed &&
        row.lastError?.startsWith("max_attempts_exceeded(") == true
    val canDrop: Boolean get() = row.status == PendingMutationStatus.Failed || row.status == PendingMutationStatus.Conflict
}

/** Publishes original intent; UpdateGoalDispatcher is the only Android PATCH writer. */
class GoalEditRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val requestAdapter: JsonAdapter<GoalUpdateRequestDto>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
) : GoalEditActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Goal edit")

    override fun currentAccess(): LedgerAccessContext? = guard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, ledgerRoleCanModify(apiProvider.currentLedgerRole()))
    }

    override fun observeAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override suspend fun currency(binding: LogicalSessionBinding): Result<CurrencyCode> = errors.safeCall {
        guard.bindExact(binding).call { api ->
            val capability = api.runtimeCompatibility().capabilities.currency
            val currency = CurrencyCode.fromStorageKeyOrNull(capability.homeCurrencyCode)
            require(currency != null && capability.minorUnitExponent == currency.minorUnitDigits &&
                capability.readCompatibility == "compatible") { "暂时无法确认目标币种，请重试连接。" }
            currency
        }
    }

    override fun observeEdits(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingGoalEdit>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.UpdateGoal), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList()
            else rows.filter { it.ownerKey == binding.ownerKey && it.ledgerId == binding.ledgerId &&
                it.targetId == "goal:$publicId" }.map { row ->
                val request = requestAdapter.readGoalUpdate(row)
                val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }
                PendingGoalEdit(row, request, receipt?.takeIf {
                    it.publicId == publicId && it.ledgerId == binding.ledgerId
                }?.toDomain())
            }
        }

    override suspend fun save(binding: LogicalSessionBinding, goal: Goal, update: GoalUpdate): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(binding)
        require(currentAccess()?.canModify == true) { "当前角色为只读，无法修改账本。" }
        require(goal.ledgerId == binding.ledgerId && goal.isSpendingLimit && !goal.isArchived) { "请重新打开这个目标。" }
        require(goal.rowVersion > 0 && update.expectedRowVersion == goal.rowVersion) { "请刷新目标后核对修改。" }
        val clean = update.validatedGoalUpdate().getOrThrow()
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
            type = PendingMutationType.UpdateGoal, targetId = "goal:${goal.publicId}",
            payloadJson = requestAdapter.toJson(clean.toRequest().copy(expectedRowVersion = 0)),
            expectedRowVersion = goal.rowVersion, idempotencyKey = UUID.randomUUID().toString(),
        ), validateTargetRows = { rows ->
            require(rows.none { it.status != PendingMutationStatus.Done }) { "这个目标还有待处理的修改，请先核对原提交。" }
        })
    }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingGoalEdit, drop: Boolean): Result<Unit> =
        errors.safeCall {
            val bound = guard.bindExact(binding)
            val current = requireNotNull(outbox.activeForTarget(bound, pending.row.targetId).firstOrNull { it.id == pending.row.id }) { "提交状态已变化，请重新核对。" }
            require(current == pending.row) { "提交状态已变化，请重新核对。" }
            require(drop && pending.canDrop || !drop && pending.canRetry && currentAccess()?.canModify == true) {
                "请核对原提交后继续。"
            }
            val changed = when (current.status) {
                PendingMutationStatus.Conflict -> outbox.resolveConflict(current.id, ConflictResolution.DropMine, bound)
                PendingMutationStatus.Failed -> outbox.resolveFailed(current.id,
                    if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
                else -> false
            }
            check(changed) { "提交状态已变化，请重新核对。" }
        }
}
