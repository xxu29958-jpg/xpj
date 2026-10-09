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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException

private class IncomeQueryReplaced : IllegalStateException("已有更新的收入读取，请重试。")
private data class IncomeReadQuery(val kind: String, val tag: String)
private data class IncomePublishedRead(val sequence: Long, val result: Result<StatsProjectionCacheEntity>)

/** IncomePlan's canonical reads. Neither a draft nor a command receipt is a query snapshot. */
internal class IncomeQueryReader(
    apiProvider: ApiServiceProvider,
    internal val dao: IncomeQueryCacheDao,
    internal val coordinator: LocalLedgerSessionCoordinator,
) {
    internal val guard = LedgerRequestGuard(apiProvider)
    internal val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "IncomePlan")
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val listingAdapter by lazy { moshi.adapter(IncomePlanListResponseDto::class.java) }
    private val historyAdapter by lazy { moshi.adapter(IncomeHistoryResponseDto::class.java) }
    private val latest = ConcurrentHashMap<String, IncomePublishedRead>()
    internal val dispatches = ConcurrentHashMap<Long, IncomeWriteProtection>()
    val accessDenials = coordinator.snapshotAccessDenials.filterNotNull()

    suspend fun listing(binding: LogicalSessionBinding, status: String): Result<ReadSnapshot<IncomePlanListResponseDto>> = withContext(Dispatchers.IO) {
        read(binding, IncomeReadQuery("income_list", status), listingAdapter, { it.validateIncomeListing(status) }) { api -> api.listIncomePlans(status) }
    }

    suspend fun history(binding: LogicalSessionBinding, publicId: String, before: Long?): Result<ReadSnapshot<IncomeHistoryResponseDto>> = withContext(Dispatchers.IO) {
        read(binding, IncomeReadQuery("income_history", "$publicId:20:$before"), historyAdapter,
            { it.validateIncomeHistory(binding, publicId, before) }) { api ->
            require(publicId.isNotBlank() && (before == null || before > 0)) { "收入历史范围不正确。" }
            api.incomePlanHistory(publicId, 20, before)
        }
    }

    private suspend fun <T> read(binding: LogicalSessionBinding, query: IncomeReadQuery, adapter: JsonAdapter<T>,
        validate: (T) -> Unit, fetch: suspend (ApiService) -> T): Result<ReadSnapshot<T>> {
        val result = readOnce(binding, query, adapter, validate, fetch)
        // Retry only when a newer accepted GET could not be retained in the projection store.
        return if (result.exceptionOrNull()?.cause is IncomeQueryReplaced) readOnce(binding, query, adapter, validate, fetch) else result
    }

    private suspend fun <T> readOnce(binding: LogicalSessionBinding, query: IncomeReadQuery, adapter: JsonAdapter<T>,
        validate: (T) -> Unit, fetch: suspend (ApiService) -> T): Result<ReadSnapshot<T>> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val (kind, tag) = query
        val key = logicalBindingAdapter.toJson(binding)
        val ticket = coordinator.beginSnapshotRead()
        val queryKey = "$key|$kind|$tag"
        val protection = dao.protection(key)
        requireNoActiveIncomeWrite(key, protection.barriers.map { it.tag })
        val value = try {
            bound.call { fetch(it) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, key, failure)
            if (error.code() == 404) retireMissingQuery(ticket, bound, key, query, failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                latest[queryKey]?.result?.exceptionOrNull()?.let { throw it }
                val saved = dao.cached(key, kind, tag, protection) ?: throw error
                check(saved.ledgerId == binding.ledgerId)
                val cached = requireNotNull(adapter.fromJson(saved.responseJson))
                validate(cached)
                ReadSnapshot(cached, saved.fetchedAt, fromCache = true)
            }
        }
        validate(value)
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            requireNoActiveIncomeWrite(key, protection.barriers.map { it.tag })
            val published = latest[queryKey]
            if (published != null && published.sequence > ticket.sequence) {
                // Concurrent consumers share the newer confirmed GET. Starting another request must
                // not invalidate a successful reader or create a chain of competing retries.
                val acceptedRow = published.result.getOrThrow()
                val saved = dao.cached(key, kind, tag, protection) ?: throw IncomeQueryReplaced()
                if (saved != acceptedRow) throw IncomeQueryReplaced()
                check(saved.ledgerId == binding.ledgerId)
                val accepted = requireNotNull(adapter.fromJson(saved.responseJson))
                validate(accepted)
                return@acceptSnapshotRead ReadSnapshot(accepted, saved.fetchedAt, fromCache = false)
            }
            val fetchedAt = Instant.now().toString()
            val row = StatsProjectionCacheEntity(key, binding.ledgerId, kind, "", tag, "", "UTC", adapter.toJson(value), fetchedAt)
            // A complete current listing reconciles interrupted writes; a historical page cannot do so.
            val settled = if (kind == "income_list") protection.barriers.map { it.tag }.toSet() else emptySet()
            try { dao.acceptFresh(row, protection, settled, cacheAllowed) }
            catch (_: SQLiteException) { /* A storage failure cannot erase an authorized fresh GET. */ }
            latest[queryKey] = IncomePublishedRead(ticket.sequence, Result.success(row))
            ReadSnapshot(value, fetchedAt, fromCache = false)
        }
    }

    private suspend fun retireMissingQuery(ticket: SnapshotReadTicket, bound: BoundLedgerRequest, key: String,
        query: IncomeReadQuery, failure: RepositoryException) {
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) {
            val queryKey = "$key|${query.kind}|${query.tag}"
            if (ticket.sequence >= (latest[queryKey]?.sequence ?: 0)) {
                latest[queryKey] = IncomePublishedRead(ticket.sequence, Result.failure(failure))
                dao.remove(key, query.kind, query.tag)
            }
        }
    }
}
