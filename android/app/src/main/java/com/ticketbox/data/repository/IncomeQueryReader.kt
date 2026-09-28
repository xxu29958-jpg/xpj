package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.IncomeQueryCacheDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.IncomeHistoryResponseDto
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.flow.filterNotNull
import retrofit2.HttpException

private class IncomeQueryReplaced : IllegalStateException("已有更新的收入读取，请重试。")

/** IncomePlan's canonical reads. Neither a draft nor a command receipt is a query snapshot. */
internal class IncomeQueryReader(
    apiProvider: ApiServiceProvider,
    internal val dao: IncomeQueryCacheDao,
    internal val coordinator: LocalLedgerSessionCoordinator,
) {
    internal val guard = LedgerRequestGuard(apiProvider)
    internal val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "IncomePlan")
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val listingAdapter = moshi.adapter(IncomePlanListResponseDto::class.java)
    private val historyAdapter = moshi.adapter(IncomeHistoryResponseDto::class.java)
    private val latest = ConcurrentHashMap<String, Long>()
    internal val dispatches = ConcurrentHashMap<Long, IncomeWriteProtection>()
    val accessDenials = coordinator.snapshotAccessDenials.filterNotNull()

    suspend fun listing(binding: LogicalSessionBinding, status: String): Result<ReadSnapshot<IncomePlanListResponseDto>> =
        read(binding, "income_list", status, listingAdapter, { it.validateIncomeListing(status) }) { api -> api.listIncomePlans(status) }

    suspend fun history(binding: LogicalSessionBinding, publicId: String, before: Long?): Result<ReadSnapshot<IncomeHistoryResponseDto>> =
        read(binding, "income_history", "$publicId:20:$before", historyAdapter,
            { it.validateIncomeHistory(binding, publicId, before) }) { api ->
            require(publicId.isNotBlank() && (before == null || before > 0)) { "收入历史范围不正确。" }
            api.incomePlanHistory(publicId, 20, before)
        }

    private suspend fun <T> read(binding: LogicalSessionBinding, kind: String, tag: String, adapter: JsonAdapter<T>,
        validate: (T) -> Unit, fetch: suspend (ApiService) -> T): Result<ReadSnapshot<T>> {
        val result = readOnce(binding, kind, tag, adapter, validate, fetch)
        // Overview and management can request the same projection together; restore the superseded reader once.
        return if (result.exceptionOrNull()?.cause is IncomeQueryReplaced) readOnce(binding, kind, tag, adapter, validate, fetch) else result
    }

    private suspend fun <T> readOnce(binding: LogicalSessionBinding, kind: String, tag: String, adapter: JsonAdapter<T>,
        validate: (T) -> Unit, fetch: suspend (ApiService) -> T): Result<ReadSnapshot<T>> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val key = logicalBindingAdapter.toJson(binding)
        val ticket = coordinator.beginSnapshotRead()
        val queryKey = "$key|$kind|$tag"
        latest[queryKey] = ticket.sequence
        val protection = dao.protection(key)
        requireNoActiveIncomeWrite(key, protection.barriers.map { it.tag })
        val value = try {
            bound.call { fetch(it) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, key, failure)
            if (error.code() == 404 && bound.isStillActive()) dao.remove(key, kind, tag)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                if (latest[queryKey] != ticket.sequence) throw IncomeQueryReplaced()
                val saved = dao.cached(key, kind, tag, protection) ?: throw error
                check(saved.ledgerId == binding.ledgerId)
                val cached = requireNotNull(adapter.fromJson(saved.responseJson))
                validate(cached)
                ReadSnapshot(cached, saved.fetchedAt, fromCache = true)
            }
        }
        validate(value)
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            if (latest[queryKey] != ticket.sequence) throw IncomeQueryReplaced()
            requireNoActiveIncomeWrite(key, protection.barriers.map { it.tag })
            val fetchedAt = Instant.now().toString()
            val row = StatsProjectionCacheEntity(key, binding.ledgerId, kind, "", tag, "", "UTC", adapter.toJson(value), fetchedAt)
            // A complete current listing reconciles interrupted writes; a historical page cannot do so.
            val settled = if (kind == "income_list") protection.barriers.map { it.tag }.toSet() else emptySet()
            try { dao.acceptFresh(row, protection, settled, cacheAllowed) }
            catch (_: SQLiteException) { /* A storage failure cannot erase an authorized fresh GET. */ }
            ReadSnapshot(value, fetchedAt, fromCache = false)
        }
    }
}
