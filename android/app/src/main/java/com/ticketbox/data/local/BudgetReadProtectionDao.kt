package com.ticketbox.data.local

import androidx.room.Transaction

data class BudgetReadState(val epoch: Long, val barrier: StatsProjectionCacheEntity?)

/** Inherited Room transactions use ExpenseDao's existing projection queries and table. */
interface BudgetReadProtectionDao {
    suspend fun statsProjections(bindingKey: String, kind: String, month: String,
        tag: String, timezone: String): List<StatsProjectionCacheEntity>
    suspend fun budgetSnapshotsForMonth(bindingKey: String, month: String): List<StatsProjectionCacheEntity>
    suspend fun deleteStatsProjection(snapshot: StatsProjectionCacheEntity)
    suspend fun saveStatsProjection(snapshot: StatsProjectionCacheEntity)

    @Transaction
    suspend fun budgetReadState(bindingKey: String, month: String) = BudgetReadState(
        statsProjections(bindingKey, "budget_read_epoch", month, "", "UTC").singleOrNull()?.responseJson?.toLong() ?: 0L,
        statsProjections(bindingKey, "budget_restore_barrier", month, "", "UTC").singleOrNull(),
    )

    @Transaction
    suspend fun clearCurrentBudgetSnapshots(bindingKey: String, month: String) {
        budgetSnapshotsForMonth(bindingKey, month).forEach { deleteStatsProjection(it) }
        statsProjections(bindingKey, "budget_history", month, "", "UTC").forEach { deleteStatsProjection(it) }
    }

    @Transaction
    suspend fun advanceBudgetReadEpoch(basis: StatsProjectionCacheEntity) {
        val epoch = budgetReadState(basis.bindingKey, basis.month).epoch
        saveStatsProjection(basis.copy(kind = "budget_read_epoch", responseJson = Math.addExact(epoch, 1L).toString()))
    }

    @Transaction
    suspend fun beginBudgetRestore(barrier: StatsProjectionCacheEntity) {
        check(budgetReadState(barrier.bindingKey, barrier.month).barrier == null) { "原预算恢复结果尚需联网核对，请先重新读取预算。" }
        advanceBudgetReadEpoch(barrier)
        saveStatsProjection(barrier)
    }

    @Transaction
    suspend fun finishBudgetRestore(barrier: StatsProjectionCacheEntity, accepted: Boolean) {
        check(budgetReadState(barrier.bindingKey, barrier.month).barrier == barrier) { "预算恢复状态已变化，请重新读取。" }
        if (accepted) clearCurrentBudgetSnapshots(barrier.bindingKey, barrier.month)
        advanceBudgetReadEpoch(barrier)
        deleteStatsProjection(barrier)
    }

    @Transaction
    suspend fun budgetSnapshotIfCurrent(query: StatsProjectionCacheEntity, expected: BudgetReadState,
        requireSettled: Boolean): StatsProjectionCacheEntity? {
        check(budgetReadState(query.bindingKey, query.month) == expected) { "预算已变化，请重新读取。" }
        if (expected.barrier != null && (query.kind == "budget" || query.tag.isEmpty())) {
            check(!requireSettled) { "预算恢复结果尚需联网核对，请重新读取。" }
            return null
        }
        return statsProjections(query.bindingKey, query.kind, query.month, query.tag, query.timezone).singleOrNull()
    }

    /** A complete monthly GET can settle an unknown restore; an individual history page cannot. */
    @Transaction
    suspend fun acceptBudgetSnapshot(query: StatsProjectionCacheEntity, expected: BudgetReadState): Boolean {
        check(budgetReadState(query.bindingKey, query.month) == expected) { "预算已变化，请重新读取。" }
        expected.barrier?.let {
            if (query.kind == "budget") finishBudgetRestore(it, accepted = true)
            else if (query.tag.isEmpty()) return false
        }
        saveStatsProjection(query)
        return true
    }

}
