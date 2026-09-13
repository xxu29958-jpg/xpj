package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.util.UUID

/** Original budget commands and their recovery, shared by the editor and global sync. */
interface BudgetSaveActions {
    fun describeSave(row: OutboxRow): PendingBudgetSave?
    fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<PendingBudgetSave>>
    suspend fun recoverSave(expectedBinding: LogicalSessionBinding, pending: PendingBudgetSave, drop: Boolean): Result<Unit>
    suspend fun enqueueSave(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<Long>
}

/** The queue owns submitted intentions; query/advice caches never become command state. */
class BudgetSaveRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val saveAdapter: JsonAdapter<BudgetSavePayload>,
    private val receiptAdapter: JsonAdapter<BudgetMonthlyDto>,
) : BudgetSaveActions {
    private val ledgerRequestGuard = LedgerRequestGuard(apiProvider)
    private val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Budget",
        statusMessages = mapOf(404 to "预算不存在。"),
    )

    override fun observeSaves(expectedBinding: LogicalSessionBinding): Flow<List<PendingBudgetSave>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.SaveMonthlyBudget), includeCompleted = true).map { rows ->
            if (ledgerRequestGuard.captureLogicalBinding() != expectedBinding) emptyList()
            else rows.mapNotNull(::describeSave)
        }

    override fun describeSave(row: OutboxRow): PendingBudgetSave? {
        val binding = ledgerRequestGuard.captureLogicalBinding() ?: return null
        val origin = canonicalServerOriginOrNull(binding.serverUrl) ?: return null
        if (row.type != PendingMutationType.SaveMonthlyBudget ||
            row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != origin) return null
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it)?.toDomain() }.getOrNull() }
        val intent = saveAdapter.readSupportedBudgetSave(row.payloadJson)?.takeIf { it.matches(row) }
        return PendingBudgetSave(row, intent, receipt)
    }

    override suspend fun recoverSave(expectedBinding: LogicalSessionBinding, pending: PendingBudgetSave, drop: Boolean): Result<Unit> = errorHandler.safeCall {
        val bound = ledgerRequestGuard.bindExact(expectedBinding)
        val original = checkNotNull(describeSave(pending.row)) { "原预算提交不属于当前连接，请重新核对。" }
        check(drop || ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读，无法修改账本。" }
        check(drop || original.canRetry) {
            "无法确认原预算提交的格式，请保留记录并核对。"
        }
        when (pending.row.status) {
            PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(pending.row.id, ConflictResolution.DropMine, bound)
            PendingMutationStatus.Failed -> outbox.resolveFailed(pending.row.id,
                if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
            else -> Unit
        }
        Unit
    }

    override suspend fun enqueueSave(
        expectedBinding: LogicalSessionBinding,
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<Long> {
        if (!ledgerRoleCanModify(apiProvider.currentLedgerRole())) {
            return Result.failure(RepositoryException("当前角色为只读，无法修改账本。"))
        }
        val cleanMonth = validatedBudgetMonth(month)
            .getOrElse { return Result.failure(it) }
        return errorHandler.safeCall {
            val bound = ledgerRequestGuard.bindExact(expectedBinding)
            check(CurrencyCode.fromStorageKeyOrNull(update.homeCurrencyCode) != null) { "预算币种无法确认，请重新读取预算。" }
            check(update.expectedRowVersion == null || update.expectedRowVersion > 0) { "预算版本无法确认，请重新读取预算。" }
            val payload = BudgetSavePayload(1, cleanMonth, currentBudgetTimezoneId(), update.toRequest().copy(expectedRowVersion = null))
            outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
                type = PendingMutationType.SaveMonthlyBudget, targetId = monthlyBudgetTarget(cleanMonth),
                payloadJson = saveAdapter.toJson(payload), expectedRowVersion = update.expectedRowVersion ?: 0L,
                idempotencyKey = UUID.randomUUID().toString()), validateTargetRows = { rows ->
                    check(rows.isEmpty()) { "这月预算有待处理的保存，请先查看原提交的同步结果。" }
                })
        }
    }
}
