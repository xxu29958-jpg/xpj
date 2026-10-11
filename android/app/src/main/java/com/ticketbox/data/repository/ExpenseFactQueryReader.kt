package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseFactQueryCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseRevisionPage
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

/** The existing fact page's query owner; cached history never acknowledges an accepted command. */
internal class ExpenseFactQueryReader(private val core: ExpenseRepositoryCore) {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val bundleAdapter by lazy { moshi.adapter(ExpenseFactBundleDto::class.java) }
    private val revisionsAdapter by lazy { moshi.adapter(ExpenseRevisionPageDto::class.java) }
    private val bindingAdapter by lazy { moshi.adapter(LogicalSessionBinding::class.java) }
    private val mutex = Mutex()
    private data class AcceptedRead(val ticket: SnapshotReadTicket, val epoch: Any, val snapshot: ExpenseFactQueryCacheEntity)
    private val acceptedReads = mutableMapOf<String, AcceptedRead>()
    private val resourceEpochs = mutableMapOf<String, Any>()

    suspend fun bundle(id: Long, binding: LogicalSessionBinding?): Result<ReadSnapshot<ExpenseFactBundle>> = withContext(Dispatchers.IO) {
        read(id, binding, FactQuery("bundle", bundleAdapter, { api -> api.expenseFactBundle(id.toString()) },
            validate = { require(it.root.id == id) { "账单读取范围不一致。" } },
            publish = { wire, bound ->
                val projection = wire.toCacheProjection(bound.ledgerId)
                try {
                    core.expenseDao.applyExpenseFactBundle(bound.ledgerId, projection.root, projection.activeOffsets)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: SQLiteException) {
                    // This fresh GET remains usable if its rebuildable projection cannot be saved.
                }
            })).map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }
    }

    suspend fun revisions(id: Long, page: Int, pageSize: Int, snapshot: com.ticketbox.domain.model.ExpenseHistorySnapshot?, binding: LogicalSessionBinding?):
        Result<ReadSnapshot<ExpenseRevisionPage>> = withContext(Dispatchers.IO) {
        read(id, binding, FactQuery("history:$pageSize:$page:${snapshot?.revision}:${snapshot?.offsetId}", revisionsAdapter,
            { api -> api.expenseRevisions(id, page, pageSize, snapshot?.revision, snapshot?.offsetId) },
            validate = { require(it.page == page && it.pageSize == pageSize &&
                it.offsetSnapshotId != null && (snapshot == null || (it.snapshotRevision == snapshot.revision &&
                it.offsetSnapshotId == snapshot.offsetId)) &&
                it.items.all { row -> row.offsetPublicId != null || row.revisionNumber <= it.snapshotRevision }) {
                    "账单历史快照不一致，请重新读取。" } }))
            .map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }
    }

    private data class FactQuery<T>(val key: String, val adapter: JsonAdapter<T>, val fetch: suspend (ApiService) -> T,
        val validate: (T) -> Unit, val publish: suspend (T, BoundLedgerRequest) -> Unit = { _, _ -> })

    private suspend fun <T> read(id: Long, binding: LogicalSessionBinding?, query: FactQuery<T>): Result<ReadSnapshot<T>> = core.errorHandler.safeCall {
        val bound = if (binding == null) core.ledgerRequestGuard.bind() else core.ledgerRequestGuard.bindExact(binding)
        val bindingKey = bindingAdapter.toJson(bound.logicalBinding)
        val resource = "$bindingKey|$id"
        val key = "$resource|${query.key}"
        val ticket = core.sessionCoordinator.beginSnapshotRead()
        val epoch = mutex.withLock { resourceEpochs.getOrPut(resource) { Any() } }
        val wire = try {
            bound.call { query.fetch(it) }
        } catch (error: HttpException) {
            val failure = core.errorHandler.httpFailure(error)
            core.sessionCoordinator.rejectSnapshotAccess(bound, bindingKey, failure)
            if (failure.httpStatusCode == 404) core.sessionCoordinator.acceptSnapshotRead(ticket, bound, false) {
                mutex.withLock {
                    resourceEpochs[resource] = Any()
                    core.expenseDao.retireExpenseFactRead(bindingKey, bound.ledgerId, id)
                }
            }
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall core.sessionCoordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                mutex.withLock {
                    requireCurrent(resource, epoch)
                    val saved = core.expenseDao.factSnapshot(bindingKey, id, query.key) ?: throw error
                    savedRead(query, saved, fromCache = true)
                }
            }
        }
        query.validate(wire)
        core.sessionCoordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            mutex.withLock {
                requireCurrent(resource, epoch)
                val accepted = acceptedReads[key]?.takeIf { it.epoch === epoch &&
                    it.ticket.generation == ticket.generation && it.ticket.sequence > ticket.sequence }
                // Starting another GET does not retire this reader. If a newer GET already
                // succeeded, share its complete snapshot without publishing the late response.
                if (accepted != null) return@withLock savedRead(query, accepted.snapshot, fromCache = false)
                val at = Instant.now().toString()
                val saved = ExpenseFactQueryCacheEntity(bindingKey, bound.ledgerId, id,
                    query.key, query.adapter.toJson(wire), at)
                query.publish(wire, bound)
                if (cacheAllowed) try {
                    core.expenseDao.saveFactSnapshot(saved)
                } catch (_: SQLiteException) {
                    // Read freshness and authorization do not depend on cache availability.
                }
                acceptedReads[key] = AcceptedRead(ticket, epoch, saved)
                ReadSnapshot(wire, at, fromCache = false)
            }
        }
    }

    private fun <T> savedRead(query: FactQuery<T>, saved: ExpenseFactQueryCacheEntity, fromCache: Boolean): ReadSnapshot<T> {
        val value = requireNotNull(query.adapter.fromJson(saved.responseJson))
        query.validate(value)
        return ReadSnapshot(value, saved.fetchedAt, fromCache)
    }

    private fun requireCurrent(resource: String, epoch: Any) {
        if (resourceEpochs[resource] !== epoch) {
            throw RepositoryException("账单读取已更新，请重试。")
        }
    }
}
