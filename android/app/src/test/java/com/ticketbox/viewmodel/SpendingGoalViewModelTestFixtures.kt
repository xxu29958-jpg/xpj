package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
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

internal data class SpendingGoalUpdateCall(
    val publicId: String,
    val update: GoalUpdate,
)

internal class RecordingSpendingGoalActions(
    private val canModify: Boolean = true,
    var goalsResult: Result<List<Goal>> = Result.success(emptyList()),
    var goalResult: Result<Goal> = Result.success(spendingGoal()),
    var updateResult: Result<Goal> = Result.success(spendingGoal(rowVersion = 2L)),
    var archiveResult: Result<Goal> = Result.success(spendingGoal(status = "archived")),
) : ReportsActions by unsupportedSpendingGoalActions() {
    val goalsCalls = mutableListOf<SpendingGoalListCall>()
    val goalCalls = mutableListOf<String>()
    val updateCalls = mutableListOf<SpendingGoalUpdateCall>()
    val archiveCalls = mutableListOf<String>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun goals(month: String?, includeArchived: Boolean): Result<List<Goal>> {
        goalsCalls += SpendingGoalListCall(month, includeArchived)
        return goalsResult
    }

    override suspend fun goal(publicId: String): Result<Goal> {
        goalCalls += publicId
        return goalResult
    }

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> {
        updateCalls += SpendingGoalUpdateCall(publicId, update)
        return updateResult
    }

    override suspend fun archiveGoal(publicId: String): Result<Goal> {
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
