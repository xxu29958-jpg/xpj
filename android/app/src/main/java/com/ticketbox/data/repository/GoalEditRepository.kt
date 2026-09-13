package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

interface GoalEditActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    fun describeEdit(row: OutboxRow): PendingGoalEdit?
    suspend fun currency(binding: LogicalSessionBinding): Result<CurrencyCode>
    fun observeEdits(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingGoalEdit>>
    suspend fun save(binding: LogicalSessionBinding, goal: Goal, update: GoalUpdate): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, pending: PendingGoalEdit, drop: Boolean): Result<Unit>
    suspend fun create(binding: LogicalSessionBinding, draft: GoalDraft): Result<Long>
    fun describeCreation(row: OutboxRow): PendingGoalCreation?
    fun observeCreations(binding: LogicalSessionBinding): Flow<List<PendingGoalCreation>>
    suspend fun recoverCreation(binding: LogicalSessionBinding, pending: PendingGoalCreation, drop: Boolean): Result<Unit>
}

data class PendingGoalEdit(val row: OutboxRow, val request: GoalUpdateRequestDto?, val confirmed: Goal?) {
    val isDone: Boolean get() = row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = request?.hasCapturedGoalCurrency() == true &&
        row.status == PendingMutationStatus.Failed && (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
        row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
    val canDrop: Boolean get() = row.status == PendingMutationStatus.Failed || row.status == PendingMutationStatus.Conflict
}

/** Owns original spending-goal commands; dispatchers are the only Android writers. */
class GoalEditRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val requestAdapter: JsonAdapter<GoalUpdateRequestDto>,
    private val receiptAdapter: JsonAdapter<GoalDto>,
    private val createAdapter: JsonAdapter<GoalCreateRequestDto>,
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

    override fun describeEdit(row: OutboxRow): PendingGoalEdit? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.UpdateGoal || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(binding.serverUrl)) return null
        val request = requestAdapter.readGoalUpdate(row)
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }
        return PendingGoalEdit(row, request, receipt?.takeIf {
            request?.acceptsGoalReceipt(row, it) == true
        }?.toDomain())
    }

    override fun observeEdits(binding: LogicalSessionBinding, publicId: String): Flow<List<PendingGoalEdit>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.UpdateGoal), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList()
            else rows.filter { it.targetId == "goal:$publicId" }.mapNotNull(::describeEdit)
        }

    override suspend fun save(binding: LogicalSessionBinding, goal: Goal, update: GoalUpdate): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(binding)
        require(currentAccess()?.canModify == true) { "当前角色为只读，无法修改账本。" }
        require(goal.ledgerId == binding.ledgerId && goal.isSpendingLimit && !goal.isArchived) { "请重新打开这个目标。" }
        require(goal.rowVersion > 0 && update.expectedRowVersion == goal.rowVersion) { "请刷新目标后核对修改。" }
        val clean = update.validatedGoalUpdate().getOrThrow()
        require(CurrencyCode.fromStorageKeyOrNull(clean.homeCurrencyCode) != null &&
            clean.homeCurrencyCode == goal.homeCurrencyCode) { "输入币种与原目标不一致，请保留金额并核对。" }
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
            type = PendingMutationType.UpdateGoal, targetId = "goal:${goal.publicId}",
            payloadJson = requestAdapter.toJson(clean.toRequest()),
            expectedRowVersion = goal.rowVersion, idempotencyKey = UUID.randomUUID().toString(),
        ), validateTargetRows = { rows ->
            require(rows.none { it.status != PendingMutationStatus.Done }) { "这个目标还有待处理的修改，请先核对原提交。" }
        })
    }

    override suspend fun recover(binding: LogicalSessionBinding, pending: PendingGoalEdit, drop: Boolean): Result<Unit> =
        errors.safeCall {
            recoverGoalSubmission(outbox, guard.bindExact(binding), pending.row, drop) { row ->
                val original = describeEdit(row)
                original != null && (drop && original.canDrop || !drop && original.canRetry && currentAccess()?.canModify == true)
            }
        }

    override suspend fun create(binding: LogicalSessionBinding, draft: GoalDraft): Result<Long> = errors.safeCall {
        val bound = guard.bindExact(binding)
        require(currentAccess()?.canModify == true) { "当前角色为只读，无法修改账本。" }
        val clean = draft.validatedGoalDraft().getOrThrow()
        val key = UUID.randomUUID().toString()
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
            type = PendingMutationType.CreateGoal, targetId = "goal_create:$key", expectedRowVersion = 0,
            payloadJson = createAdapter.toJson(clean.toRequest()), idempotencyKey = key,
        ))
    }

    override fun describeCreation(row: OutboxRow): PendingGoalCreation? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.CreateGoal || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(binding.serverUrl)) return null
        val request = createAdapter.readGoalCreation(row)
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }
        return PendingGoalCreation(row, request, receipt?.takeIf { request?.acceptsGoalCreationReceipt(row, it) == true }?.toDomain())
    }

    override fun observeCreations(binding: LogicalSessionBinding): Flow<List<PendingGoalCreation>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.CreateGoal), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList() else rows.mapNotNull(::describeCreation)
        }

    override suspend fun recoverCreation(binding: LogicalSessionBinding, pending: PendingGoalCreation, drop: Boolean): Result<Unit> =
        errors.safeCall {
            recoverGoalSubmission(outbox, guard.bindExact(binding), pending.row, drop) { row ->
                val original = describeCreation(row)
                original != null && (drop && original.canDrop || !drop && original.canRetry && currentAccess()?.canModify == true)
            }
        }
}

private suspend fun recoverGoalSubmission(outbox: OutboxRepository, bound: BoundLedgerRequest, row: OutboxRow,
    drop: Boolean, permitted: (OutboxRow) -> Boolean) {
    val current = requireNotNull(outbox.activeForTarget(bound, row.targetId).firstOrNull { it.id == row.id }) { "提交状态已变化，请重新核对。" }
    require(current == row) { "提交状态已变化，请重新核对。" }
    require(permitted(current)) { "请在原账本核对这份提交后继续。" }
    val changed = when (current.status) {
        PendingMutationStatus.Conflict -> outbox.resolveConflict(current.id, ConflictResolution.DropMine, bound)
        PendingMutationStatus.Failed -> outbox.resolveFailed(current.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
        else -> false
    }
    check(changed) { "提交状态已变化，请重新核对。" }
}
