package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.ApiService
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import retrofit2.HttpException

internal val INCOME_QUERY_MUTATION_TYPES = setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan)
private val activeIncomeWrites = ConcurrentHashMap.newKeySet<String>()
internal data class IncomeWriteProtection(val row: StatsProjectionCacheEntity, val bound: BoundLedgerRequest, val hadUnresolved: Boolean)

internal fun requireNoActiveIncomeWrite(bindingKey: String, tokens: List<String>) {
    check(tokens.none { "$bindingKey|$it" in activeIncomeWrites }) { "收入操作正在提交，请稍后重新读取。" }
}

private suspend fun IncomeQueryReader.beginWrite(binding: LogicalSessionBinding, token: String): IncomeWriteProtection {
    val bound = guard.bindExact(binding)
    val key = logicalBindingAdapter.toJson(binding)
    val row = StatsProjectionCacheEntity(key, binding.ledgerId, "income_write_barrier", "", token, "", "UTC", token, Instant.now().toString())
    activeIncomeWrites.add("$key|$token")
    try { return IncomeWriteProtection(row, bound, dao.beginWrite(row)) }
    catch (error: Exception) { activeIncomeWrites.remove("$key|$token"); throw error }
}

private fun release(protection: IncomeWriteProtection) {
    activeIncomeWrites.remove("${protection.row.bindingKey}|${protection.row.tag}")
}

internal suspend fun <T> IncomeQueryReader.directWrite(binding: LogicalSessionBinding, action: suspend (ApiService) -> T): T {
    val protection = beginWrite(binding, "direct:${UUID.randomUUID()}")
    try {
        val result = protection.bound.call { action(it) }
        withContext(NonCancellable) {
            try { dao.finishWrite(protection.row) }
            catch (_: SQLiteException) { /* The accepted result stays real; the durable barrier protects older reads. */ }
        }
        return result
    } catch (error: HttpException) {
        val failure = errors.httpFailure(error)
        withContext(NonCancellable) {
            if (error.code() == 401) coordinator.rejectSnapshotAccess(protection.bound, protection.row.bindingKey, failure)
            if (error.code() in 400..499 && error.code() != 408) {
                try { dao.finishWrite(protection.row, accepted = false) } catch (_: SQLiteException) { /* A fresh query can reconcile it. */ }
            }
        }
        throw failure
    } finally { release(protection) }
}

internal suspend fun IncomeQueryReader.prepareDispatch(row: OutboxRow) {
    val binding = requireNotNull(guard.captureLogicalBinding())
    require(row.ownerKey == binding.ownerKey && row.ledgerId == binding.ledgerId &&
        canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) { "原收入提交不属于当前连接。" }
    dispatches[row.id] = beginWrite(binding, "outbox:${row.idempotencyKey ?: row.id}")
}

internal suspend fun IncomeQueryReader.acceptedDispatch(row: OutboxRow) {
    dao.finishWrite(requireNotNull(dispatches[row.id]).row)
}

internal suspend fun IncomeQueryReader.finishDispatch(row: OutboxRow, result: DispatchResult?) {
    val protection = dispatches.remove(row.id) ?: return
    try {
        if (result is DispatchResult.Failure && result.credentialRejected) {
            coordinator.rejectSnapshotAccess(protection.bound, protection.row.bindingKey,
                RepositoryException(result.message, httpStatusCode = 401))
        }
        val rejected = result is DispatchResult.Conflict || result is DispatchResult.Discarded ||
            (result is DispatchResult.Failure && result.definitelyRejected)
        if (rejected && !protection.hadUnresolved) dao.finishWrite(protection.row, accepted = false)
    } catch (_: SQLiteException) { /* Keep durable protection until a complete current query succeeds. */ }
    finally { release(protection) }
}
