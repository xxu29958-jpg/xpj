package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

/** Rebuildable IncomePlan queries use the existing projection store, separate from original writes. */
data class IncomeReadProtection(val epoch: Long, val barriers: List<StatsProjectionCacheEntity>)

@Dao
interface IncomeQueryCacheDao {
    @Query("SELECT * FROM stats_projection_cache WHERE bindingKey = :bindingKey AND kind = :kind AND tag = :tag AND month = '' AND homeCurrencyCode = '' AND timezone = 'UTC'")
    suspend fun read(bindingKey: String, kind: String, tag: String): StatsProjectionCacheEntity?

    @Query("SELECT * FROM stats_projection_cache WHERE bindingKey = :bindingKey AND kind = 'income_write_barrier' ORDER BY tag")
    suspend fun barriers(bindingKey: String): List<StatsProjectionCacheEntity>

    @Query("DELETE FROM stats_projection_cache WHERE bindingKey = :bindingKey AND kind IN ('income_list', 'income_history')")
    suspend fun clearValues(bindingKey: String)

    @Query("DELETE FROM stats_projection_cache WHERE bindingKey = :bindingKey AND kind = :kind AND tag = :tag")
    suspend fun remove(bindingKey: String, kind: String, tag: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(row: StatsProjectionCacheEntity)

    @Transaction
    suspend fun protection(bindingKey: String): IncomeReadProtection = IncomeReadProtection(
        read(bindingKey, "income_read_epoch", "")?.responseJson?.toLong() ?: 0L, barriers(bindingKey))

    @Transaction
    suspend fun beginWrite(barrier: StatsProjectionCacheEntity): Boolean {
        val existed = read(barrier.bindingKey, barrier.kind, barrier.tag) != null
        advance(barrier)
        save(barrier)
        return existed
    }

    @Transaction
    suspend fun finishWrite(barrier: StatsProjectionCacheEntity) {
        advance(barrier)
        remove(barrier.bindingKey, "income_write_barrier", barrier.tag)
    }

    @Transaction
    suspend fun advance(basis: StatsProjectionCacheEntity) {
        val current = read(basis.bindingKey, "income_read_epoch", "")?.responseJson?.toLong() ?: 0L
        save(basis.copy(kind = "income_read_epoch", tag = "", responseJson = Math.addExact(current, 1).toString()))
        clearValues(basis.bindingKey)
    }

    @Transaction
    suspend fun cached(bindingKey: String, kind: String, tag: String, expected: IncomeReadProtection): StatsProjectionCacheEntity? {
        check(protection(bindingKey) == expected && expected.barriers.isEmpty()) { "收入提交结果待核对，请联网读取。" }
        return read(bindingKey, kind, tag)
    }

    @Transaction
    suspend fun acceptFresh(row: StatsProjectionCacheEntity, expected: IncomeReadProtection,
        settledTokens: Set<String>, cacheAllowed: Boolean) {
        check(protection(row.bindingKey) == expected) { "收入计划已变化，请重新读取。" }
        if (settledTokens.isNotEmpty()) {
            advance(row)
            expected.barriers.filter { it.tag in settledTokens }.forEach { remove(row.bindingKey, "income_write_barrier", it.tag) }
        }
        if (cacheAllowed && barriers(row.bindingKey).isEmpty()) save(row)
    }
}
