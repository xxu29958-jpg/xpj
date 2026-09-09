package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import java.lang.reflect.Proxy

/** R12-D 三个写面（goal 新建/编辑、收入计划）的账本币种 fake：listDebts 返回带 capability
 *  的页型（默认 CNY），其余方法不支持。 */
internal class CapabilityDebtActions(
    private val canModify: Boolean = true,
    var page: DebtListPage = DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "CNY"),
) : DebtActions by unsupportedDebtActions() {
    var listCalls = 0
        private set

    /** 测试延迟钩：挂起 listDebts 直至放行（模拟弱网下币种解析晚于用户点行）。 */
    var listDebtsGate: (suspend () -> Unit)? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(lens: com.ticketbox.domain.model.DebtListLens): Result<DebtListPage> {
        listCalls += 1
        listDebtsGate?.invoke()
        return Result.success(page)
    }
}

@Suppress("UNCHECKED_CAST")
private fun unsupportedDebtActions(): DebtActions = Proxy.newProxyInstance(
    DebtActions::class.java.classLoader,
    arrayOf(DebtActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedDebtActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as DebtActions

internal data class SpendingGoalListCall(
    val month: String?,
    val includeArchived: Boolean,
)

internal class RecordingSpendingGoalActions(
    private val canModify: Boolean = true,
    var goalsResult: Result<List<Goal>> = Result.success(emptyList()),
    var goalResult: Result<Goal> = Result.success(spendingGoal()),
    var archiveResult: Result<Goal> = Result.success(spendingGoal(status = "archived")),
) : ReportsActions by unsupportedSpendingGoalActions() {
    var fetchedAt = "2026-09-09T00:00:00Z"
    var fromCache = false
    val goalsCalls = mutableListOf<SpendingGoalListCall>()
    val goalCalls = mutableListOf<String>()
    var goalGate: (suspend () -> Unit)? = null
    val archiveCalls = mutableListOf<String>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun goals(month: String?, includeArchived: Boolean, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> {
        goalsCalls += SpendingGoalListCall(month, includeArchived)
        return goalsResult.map { ReadSnapshot(it, fetchedAt, fromCache) }
    }

    override suspend fun goal(publicId: String, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<Goal>> {
        goalCalls += publicId
        val result = goalResult
        goalGate?.invoke()
        return result.map { ReadSnapshot(it, fetchedAt, fromCache) }
    }

    override suspend fun archiveGoal(publicId: String, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding): Result<Goal> {
        archiveCalls += publicId
        return archiveResult
    }
}

internal fun spendingGoal(
    publicId: String = "goal-1",
    status: String = "active",
    goalType: String = "spending_limit",
    rowVersion: Long = 1L,
): Goal = Goal(
    publicId = publicId,
    ledgerId = "owner",
    name = "本月外卖",
    goalType = goalType,
    period = "monthly",
    month = "2026-07",
    category = "餐饮",
    targetAmountCents = 20_000,
    spentAmountCents = 8_000,
    remainingAmountCents = 12_000,
    progressPercent = 40,
    progressState = if (status == "archived") GoalProgressState.Archived else GoalProgressState.OnTrack,
    status = status,
    createdAt = "2026-07-01T00:00:00Z",
    updatedAt = "2026-07-02T00:00:00Z",
    rowVersion = rowVersion,
    archivedAt = if (status == "archived") "2026-07-03T00:00:00Z" else null,
    homeCurrencyCode = "CNY",
)

@Suppress("UNCHECKED_CAST")
private fun unsupportedSpendingGoalActions(): ReportsActions = Proxy.newProxyInstance(
    ReportsActions::class.java.classLoader,
    arrayOf(ReportsActions::class.java),
) { _, method, _ ->
    when (method.name) {
        "toString" -> "UnsupportedSpendingGoalActions"
        else -> throw UnsupportedOperationException(method.name)
    }
} as ReportsActions

internal class RecordingGoalEdits : com.ticketbox.data.repository.GoalEditActions {
    val access = kotlinx.coroutines.flow.MutableStateFlow<com.ticketbox.data.repository.LedgerAccessContext?>(
        com.ticketbox.data.repository.LedgerAccessContext(com.ticketbox.data.repository.LogicalSessionBinding(
            "https://goal.example", "owner", "test-owner", "session-1", "binding-1"), true))
    val rows = kotlinx.coroutines.flow.MutableStateFlow<List<com.ticketbox.data.repository.PendingGoalEdit>>(emptyList())
    var currencyResult = Result.success(com.ticketbox.domain.model.CurrencyCode.CNY)
    var currencyGate: (suspend () -> Unit)? = null
    var saveGate: (suspend () -> Unit)? = null
    var saveResult = Result.success(1L)
    val saves = mutableListOf<GoalUpdate>()
    val createCalls = mutableListOf<com.ticketbox.domain.model.GoalDraft>()
    var createGate: (suspend () -> Unit)? = null
    val creations = kotlinx.coroutines.flow.MutableStateFlow<List<com.ticketbox.data.repository.PendingGoalCreation>>(emptyList())
    override fun describeCreation(row: com.ticketbox.data.repository.OutboxRow) = creations.value.firstOrNull { it.row.id == row.id }
    override fun observeCreations(binding: com.ticketbox.data.repository.LogicalSessionBinding) = creations
    override suspend fun create(binding: com.ticketbox.data.repository.LogicalSessionBinding,
        draft: com.ticketbox.domain.model.GoalDraft): Result<Long> {
        createCalls += draft
        createGate?.invoke()
        if (access.value?.binding != binding) return Result.failure(IllegalStateException("Binding changed"))
        val request = com.ticketbox.data.remote.dto.GoalCreateRequestDto(name = draft.name, month = draft.month,
            category = draft.category, targetAmountCents = draft.targetAmountCents, homeCurrencyCode = draft.homeCurrencyCode)
        val row = com.ticketbox.data.repository.OutboxRow(1, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            com.ticketbox.data.local.PendingMutationType.CreateGoal, "goal_create:original-key", "{}", 0,
            com.ticketbox.data.local.PendingMutationStatus.Pending, 0, null, "2026-09-01", null, null, "original-key")
        creations.value = listOf(com.ticketbox.data.repository.PendingGoalCreation(row, request, null))
        return Result.success(row.id)
    }
    override suspend fun recoverCreation(binding: com.ticketbox.data.repository.LogicalSessionBinding,
        pending: com.ticketbox.data.repository.PendingGoalCreation, drop: Boolean): Result<Unit> {
        if (drop) creations.value = creations.value.filterNot { it.row.id == pending.row.id }
        return Result.success(Unit)
    }
    override fun currentAccess() = access.value
    override fun observeAccess() = access
    override fun describeEdit(row: com.ticketbox.data.repository.OutboxRow) = rows.value.firstOrNull { it.row.id == row.id }
    override suspend fun currency(binding: com.ticketbox.data.repository.LogicalSessionBinding): Result<com.ticketbox.domain.model.CurrencyCode> {
        val result = currencyResult
        currencyGate?.invoke()
        return result
    }
    override fun observeEdits(binding: com.ticketbox.data.repository.LogicalSessionBinding, publicId: String) = rows
    override suspend fun save(binding: com.ticketbox.data.repository.LogicalSessionBinding, goal: Goal, update: GoalUpdate): Result<Long> {
        saves += update
        saveGate?.invoke()
        return saveResult
    }
    override suspend fun recover(binding: com.ticketbox.data.repository.LogicalSessionBinding,
        pending: com.ticketbox.data.repository.PendingGoalEdit, drop: Boolean) = Result.success(Unit)
}
