package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.BudgetReadState
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import retrofit2.HttpException

/** Budget queries and history share the existing projection store's durable restore protection. */
internal class BudgetReadProtection(private val dao: ExpenseDao) {
    companion object {
        private val active = ConcurrentHashMap.newKeySet<String>()
        private fun requireInactive(state: BudgetReadState) {
            val token = state.barrier?.responseJson
            check(token == null || token !in active) { "预算正在恢复，请稍后重新读取。" }
        }
    }

    suspend fun beginRead(key: String, month: String): BudgetReadState = dao.budgetReadState(key, month).also(::requireInactive)

    suspend fun requireCurrent(key: String, month: String, expected: BudgetReadState) {
        requireInactive(expected)
        check(dao.budgetReadState(key, month) == expected) { "预算已变化，请重新读取。" }
    }

    suspend fun publish(query: StatsProjectionCacheEntity, state: BudgetReadState): Boolean {
        requireCurrent(query.bindingKey, query.month, state)
        return try { dao.acceptBudgetSnapshot(query, state) }
        catch (_: SQLiteException) { false } // A valid GET remains usable; failed settlement leaves the barrier durable.
    }

    suspend fun <T> restore(binding: LogicalSessionBinding, month: String, send: suspend () -> T): T {
        val token = UUID.randomUUID().toString()
        val barrier = StatsProjectionCacheEntity(logicalBindingAdapter.toJson(binding), binding.ledgerId,
            "budget_restore_barrier", month, "", "", "UTC", token, Instant.now().toString())
        active.add(token)
        try {
            try { dao.beginBudgetRestore(barrier) }
            catch (error: SQLiteException) {
                throw RepositoryException("预算恢复尚未发送：本地读取保护无法保存，请稍后再试。", cause = error)
            }
            val result = try { send() } catch (error: HttpException) {
                if (error.code() in setOf(400, 401, 403, 404, 405, 409, 410, 412, 422)) settle(barrier, accepted = false)
                throw error
            }
            settle(barrier, accepted = true)
            return result
        } finally { active.remove(token) }
    }

    private suspend fun settle(barrier: StatsProjectionCacheEntity, accepted: Boolean) = withContext(NonCancellable) {
        try { dao.finishBudgetRestore(barrier, accepted) }
        catch (_: SQLiteException) { /* Preserve the original result; the persisted barrier still protects old reads. */ }
    }
}
