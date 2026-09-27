package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.domain.model.RecurringItem
import java.time.Instant
import java.time.YearMonth
import java.util.TimeZone
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

/** Complete recurring GETs in the existing Room projection store; no command receipt seeds a read. */
internal class RecurringQueryReader(
    apiProvider: ApiServiceProvider,
    private val dao: ExpenseDao,
    private val coordinator: LocalLedgerSessionCoordinator,
) {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "Recurring")
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val itemsAdapter = moshi.adapter(RecurringItemListResponseDto::class.java)
    private val historyAdapter = moshi.adapter(RecurringHistoryPageDto::class.java)
    private val occurrenceAdapter = moshi.adapter(RecurringOccurrenceDto::class.java)
    private val mutex = Mutex()
    private val latestRequests = mutableMapOf<String, Long>()
    private val localInvalidation = AtomicLong()
    private val retiredBindings = ConcurrentHashMap.newKeySet<String>()
    val readAccessDenials = coordinator.snapshotAccessDenials.filterNotNull()

    /** Reminder reads share binding/refusal coordination but never consume or publish a UI cache. */
    suspend fun freshItems(binding: LogicalSessionBinding, status: String?, archived: Boolean, month: String?): Result<List<RecurringItem>> =
        errors.safeCall {
            val bound = guard.bindExact(binding)
            val ticket = coordinator.beginSnapshotRead()
            val generation = localInvalidation.get()
            val key = logicalBindingAdapter.toJson(binding)
            val epoch = dao.recurringReadEpoch(key)?.toLong() ?: 0L
            val page = try {
                bound.call { it.recurringItems(status, archived, month, TimeZone.getDefault().id) }
            } catch (error: HttpException) {
                val failure = errors.httpFailure(error)
                coordinator.rejectSnapshotAccess(bound, logicalBindingAdapter.toJson(binding), failure)
                throw failure
            }
            require(page.items.all { it.ledgerId == binding.ledgerId }) { "固定支出所属账本不匹配。" }
            coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) {
                check(localInvalidation.get() == generation && (dao.recurringReadEpoch(key)?.toLong() ?: 0L) == epoch) {
                    "固定支出已接受修改，请重新读取。"
                }
                page.items.map { it.toDomain() }
            }
        }

    suspend fun invalidate(binding: LogicalSessionBinding) {
        guard.bindExact(binding).requireStillActive()
        localInvalidation.incrementAndGet()
        val key = logicalBindingAdapter.toJson(binding)
        retiredBindings.add(key)
        dao.invalidateRecurringSnapshots(key, binding.ledgerId)
        retiredBindings.remove(key)
    }

    suspend fun invalidateDirect(binding: LogicalSessionBinding) {
        try {
            invalidate(binding)
        } catch (_: SQLiteException) {
            // Rebuildable storage cannot turn a direct command into a failure or block its existing writer.
        }
    }

    suspend fun invalidateAccepted(row: OutboxRow) {
        val binding = requireNotNull(guard.captureLogicalBinding())
        require(row.ownerKey == binding.ownerKey && row.ledgerId == binding.ledgerId &&
            canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
            "原固定支出提交不属于当前连接。"
        }
        invalidate(binding)
    }

    suspend fun items(binding: LogicalSessionBinding, status: String?, archived: Boolean, month: String?):
        Result<ReadSnapshot<List<RecurringItem>>> = errors.safeCall {
        month?.let { require(YearMonth.parse(it).toString() == it) { "固定支出月份范围不正确。" } }
        val scope = scope(binding, "recurring_items", month.orEmpty(), "${status.orEmpty()}:$archived", TimeZone.getDefault().id)
        read(binding, scope, itemsAdapter, { recurringItems(status, archived, month, scope.timezone) }) { page ->
            require(page.items.map { it.publicId }.distinct().size == page.items.size) { "固定支出列表包含重复记录。" }
            page.items.forEach { item ->
                require(item.ledgerId == binding.ledgerId && item.publicId.isNotBlank() && item.rowVersion > 0 &&
                    (status == null || item.status == status) && (status != null || archived || item.status != "archived")) {
                    "固定支出所属账本或读取范围不匹配。"
                }
            }
        }.map { ReadSnapshot(it.value.items.map { row -> row.toDomain() }, it.fetchedAt, it.fromCache) }.getOrThrow()
    }

    suspend fun history(binding: LogicalSessionBinding, publicId: String, before: Long?): Result<ReadSnapshot<RecurringHistoryPageDto>> =
        errors.safeCall {
            require(publicId.isNotBlank() && (before == null || before > 0)) { "固定支出历史范围不正确。" }
            read(binding, scope(binding, "recurring_history", "", "$publicId:50:$before", "UTC"), historyAdapter,
                { recurringHistory(publicId, 50, before) }) { it.validateHistory(binding, publicId, before) }.getOrThrow()
        }

    suspend fun occurrence(binding: LogicalSessionBinding, publicId: String, period: String): Result<ReadSnapshot<RecurringOccurrenceDto>> =
        errors.safeCall {
            require(publicId.isNotBlank() && (period == "current" || YearMonth.parse(period).toString() == period)) {
                "固定支出期次范围不正确。"
            }
            // A current read retains the server's actual period, never a locally guessed month.
            read(binding, scope(binding, "recurring_occurrence", period, publicId, "UTC"), occurrenceAdapter,
                { recurringOccurrence(publicId, period) }) { it.validateOccurrence(publicId, period) }.getOrThrow()
        }

    private suspend fun <T> read(binding: LogicalSessionBinding, query: StatsProjectionCacheEntity, adapter: JsonAdapter<T>,
        fetch: suspend ApiService.() -> T, validate: (T) -> Unit): Result<ReadSnapshot<T>> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val ticket = coordinator.beginSnapshotRead()
        val generation = localInvalidation.get()
        val epoch = dao.recurringReadEpoch(query.bindingKey)?.toLong() ?: 0L
        val key = "${query.bindingKey}|${query.kind}|${query.month}|${query.tag}|${query.timezone}"
        mutex.withLock { latestRequests[key] = ticket.sequence }
        val wire = try {
            bound.call { fetch(it) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, query.bindingKey, failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                mutex.withLock {
                    requireLatest(key, ticket)
                    check(localInvalidation.get() == generation) { "固定支出已接受修改，请重新读取。" }
                    check(query.bindingKey !in retiredBindings) { "固定支出读取已失效，请联网重新读取。" }
                    val saved = cachedQuery(query, epoch) ?: throw error
                    val value = requireNotNull(adapter.fromJson(saved.responseJson))
                    validate(value)
                    ReadSnapshot(value, saved.fetchedAt, fromCache = true)
                }
            }
        }
        validate(wire)
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            mutex.withLock {
                requireLatest(key, ticket)
                check(localInvalidation.get() == generation && (dao.recurringReadEpoch(query.bindingKey)?.toLong() ?: 0L) == epoch) {
                    "固定支出已接受修改，请重新读取。"
                }
                val fetchedAt = Instant.now().toString()
                if (cacheAllowed) try {
                    if (query.bindingKey in retiredBindings) {
                        dao.clearRecurringSnapshots(query.bindingKey)
                        retiredBindings.remove(query.bindingKey)
                    }
                    dao.saveRecurringSnapshotIfCurrent(query.copy(responseJson = adapter.toJson(wire), fetchedAt = fetchedAt),
                        epoch)
                } catch (_: SQLiteException) {
                    // The authorized GET remains usable even when rebuildable storage cannot publish it.
                }
                ReadSnapshot(wire, fetchedAt, fromCache = false)
            }
        }
    }

    private fun requireLatest(key: String, ticket: SnapshotReadTicket) {
        check(latestRequests[key] == ticket.sequence) { "固定支出已有更新的读取，请重新读取。" }
    }

    private suspend fun cachedQuery(query: StatsProjectionCacheEntity, epoch: Long): StatsProjectionCacheEntity? {
        val exact = dao.recurringSnapshotIfCurrent(query, epoch)
        if (exact != null || query.kind != "recurring_occurrence" || query.month == "current") return exact
        // Only a response whose actual period validates against the requested month can be reused below.
        return dao.recurringSnapshotIfCurrent(query.copy(month = "current"), epoch)
    }

    private fun scope(binding: LogicalSessionBinding, kind: String, month: String, tag: String, timezone: String) =
        StatsProjectionCacheEntity(logicalBindingAdapter.toJson(binding), binding.ledgerId, kind, month, tag, "", timezone, "", "")
}

private fun RecurringOccurrenceDto.validateOccurrence(id: String, requested: String) {
    require(seriesPublicId == id && seriesRowVersion > 0 && rowVersion >= 0 &&
        (requested == "current" || period == requested)) { "固定支出期次读取不匹配。" }
    YearMonth.parse(period)
    recordedDefinition?.let { original ->
        require(rowVersion > 0 && original.seriesRowVersion > 0 && original.seriesRowVersion <= seriesRowVersion) {
            "本期原定义不正确，请重新读取。"
        }
        Instant.parse(original.recordedAt)
        original.snapshot.validateDefinition()
    }
}
