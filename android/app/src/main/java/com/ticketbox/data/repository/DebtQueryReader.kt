package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.DebtQueryCachePayload
import com.ticketbox.data.local.debtCachePayload
import com.ticketbox.data.local.debtQueryCacheAdapter
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtActivityListDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtActivityPage
import com.ticketbox.domain.model.DebtListLens
import java.io.IOException
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

data class DebtReadResourceDenial(val binding: LogicalSessionBinding, val debtPublicId: String,
    val failure: RepositoryException, val generation: Long)

internal val DEBT_QUERY_MUTATION_TYPES = setOf(PendingMutationType.CreateDebt, PendingMutationType.RecordDebtRepayment,
    PendingMutationType.RecordDebtAdjustment, PendingMutationType.VoidDebt, PendingMutationType.VoidDebtRepayment,
    PendingMutationType.SplitAgreement, PendingMutationType.SetDebtKind)

private data class AcceptedDebtQuery(val query: StatsProjectionCacheEntity, val stored: DebtQueryCachePayload, val accessGeneration: Long)
private val activeDebtDirectTokens = ConcurrentHashMap.newKeySet<String>()
internal data class DebtQueryScope(val row: StatsProjectionCacheEntity, val publicId: String? = null, val directTokens: Set<String> = emptySet())
private data class DebtReadRequest(val binding: LogicalSessionBinding, val scope: DebtQueryScope,
    val ticket: SnapshotReadTicket, val localGeneration: Long, val epoch: Long, val resourceFences: Map<String, String>,
    val unpublishedAcceptance: String?, val directWasActive: Boolean)
private class DebtReadChanged : IllegalStateException("原往来提交状态已变化，请重新读取。")
private val DebtReadRequest.canRetryRepair: Boolean
    get() = !directWasActive && (unpublishedAcceptance != null || scope.directTokens.isNotEmpty())
private val DebtReadRequest.resourceFence: String?
    get() = scope.publicId?.let(resourceFences::get)
internal data class DebtReadSpec<T>(val adapter: JsonAdapter<T>, val fetch: suspend ApiService.() -> T,
    val validate: (T) -> Unit, val isNewer: (T, T) -> Boolean, val project: (T, Set<String>) -> T,
    val publicIds: (T) -> Set<String> = { emptySet() })

/** The canonical Debt GET owner; participant shells and command intents remain separate facts. */
internal class DebtQueryReader(
    apiProvider: ApiServiceProvider,
    internal val dao: ExpenseDao,
    internal val coordinator: LocalLedgerSessionCoordinator,
) {
    internal val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "Debt")
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val debtAdapter = moshi.adapter(DebtDto::class.java)
    internal val listAdapter = moshi.adapter(DebtListResponseDto::class.java)
    private val activityAdapter = moshi.adapter(DebtActivityListDto::class.java)
    private val readOwner = coordinator.readSequenceOwner
    private val mutex = Mutex()
    internal val generation = AtomicLong()
    internal val activeDirect = activeDebtDirectTokens
    private val resourceGeneration = AtomicLong()
    private val accepted = mutableMapOf<String, AcceptedDebtQuery>()
    internal val dispatchProtections = ConcurrentHashMap<Long, DebtDispatchReadProtection>()
    internal val retired = ConcurrentHashMap.newKeySet<String>()
    private val resourceDenials = MutableSharedFlow<DebtReadResourceDenial>(extraBufferCapacity = 64)
    private val localResourceDenials = ConcurrentHashMap<String, String>()
    val readAccessDenials = coordinator.snapshotAccessDenials.filterNotNull()
    val readResourceDenials = resourceDenials

    /** Participant previews remain fresh-only, but their refusals retire the same read authority. */
    suspend fun <T> freshQuery(task: DebtTask, fetch: suspend ApiService.() -> T): Result<T> = errors.safeCall {
        val bound = guard.bindExact(task.binding)
        val ticket = coordinator.beginSnapshotRead()
        val key = logicalBindingAdapter.toJson(task.binding)
        val epoch = dao.debtReadEpoch(key)?.toLong() ?: 0L
        val unpublished = dao.debtOutboxReadBarrier(key)?.responseJson
        val directTokens = dao.debtDirectBarriers(key).map { it.tag }.toSet()
        val directWasActive = hasActiveDirect(key)
        val fence = deniedResources(key)[task.debtPublicId]
        val value = fetchDebtNetwork(bound, fetch) { error ->
            val failure = errors.httpFailure(error)
            if (failure.httpStatusCode == 404 && failure.errorCode == "debt_not_found" && bound.isStillActive()) {
                rejectResource(task.binding, task.debtPublicId, failure)
            } else coordinator.rejectSnapshotAccess(bound, key, failure)
            failure
        }
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) {
            check((dao.debtReadEpoch(key)?.toLong() ?: 0L) == epoch && deniedResources(key)[task.debtPublicId] == fence)
            check(unpublished == dao.debtOutboxReadBarrier(key)?.responseJson) {
                "原往来提交已接受，请重新读取。"
            }
            check(dao.debtDirectBarriers(key).map { it.tag }.toSet() == directTokens &&
                (!directWasActive || hasActiveDirect(key))) { "原往来提交状态已变化，请重新读取。" }
            value
        }
    }

    suspend fun invalidate(binding: LogicalSessionBinding) {
        guard.bindExact(binding).requireStillActive()
        generation.incrementAndGet()
        val key = logicalBindingAdapter.toJson(binding)
        retired.add(key)
        dao.invalidateDebtSnapshots(key, binding.ledgerId)
        retired.remove(key)
    }

    suspend fun list(binding: LogicalSessionBinding, lens: DebtListLens): Result<ReadSnapshot<DebtListPage>> =
        listQuery(binding, lens.name) { debts(if (lens == DebtListLens.Payables) "payables" else null) }
            .map { ReadSnapshot(DebtListPage(it.value.items.map(DebtDto::toDomain), it.value.homeCurrencyCode), it.fetchedAt, it.fromCache) }

    suspend fun receivables(binding: LogicalSessionBinding): Result<ReadSnapshot<List<Debt>>> =
        listQuery(binding, "receivables") { debtReceivables() }
            .map { ReadSnapshot(it.value.items.map(DebtDto::toDomain), it.fetchedAt, it.fromCache) }

    suspend fun detail(binding: LogicalSessionBinding, publicId: String): Result<ReadSnapshot<Debt>> =
        read(binding, DebtQueryScope(debtScope(binding, "debt_detail", publicId), publicId), DebtReadSpec(debtAdapter, { debt(publicId) },
            validate = { validateDebt(it, binding, publicId, allowShell = true) },
            isNewer = { old, incoming -> incoming.rowVersion > old.rowVersion }, project = { value, _ -> value }))
            .map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }

    suspend fun activity(task: DebtTask, page: Int, focus: String?): Result<ReadSnapshot<DebtActivityPage>> =
        read(task.binding, DebtQueryScope(debtScope(task.binding, "debt_activity", "${task.debtPublicId}:$page:${focus.orEmpty()}"),
            task.debtPublicId), DebtReadSpec(activityAdapter, { debtActivity(task.debtPublicId, page, focus) },
            validate = { require(page > 0 && it.debtPublicId == task.debtPublicId && it.page > 0 &&
                (focus != null || it.page == page) && it.pageSize > 0 && it.total >= 0) },
            isNewer = { _, _ -> false }, project = { value, _ -> value }))
            .map { ReadSnapshot(it.value.toDomain(), it.fetchedAt, it.fromCache) }

    internal suspend fun <T> read(binding: LogicalSessionBinding, scope: DebtQueryScope,
        spec: DebtReadSpec<T>, retryRepair: Boolean = true): Result<ReadSnapshot<T>> = errors.safeCall {
        val query = scope.row
        scope.publicId?.let { require(it.isNotBlank()) }
        val bound = guard.bindExact(binding)
        val ticket = coordinator.beginSnapshotRead()
        val localGeneration = generation.get()
        val protection = dao.captureDebtReadProtection(query.bindingKey)
        val request = DebtReadRequest(binding, scope.copy(directTokens = protection.directTokens), ticket, localGeneration,
            protection.epoch,
            deniedResources(query.bindingKey),
            protection.outboxToken, hasActiveDirect(query.bindingKey))
        val wire = try {
            fetchDebtNetwork(bound, spec.fetch) { error ->
                val failure = errors.httpFailure(error)
                if (failure.httpStatusCode == 404 && failure.errorCode == "debt_not_found" &&
                    scope.publicId != null && bound.isStillActive()) {
                    rejectResource(binding, scope.publicId, failure)
                } else coordinator.rejectSnapshotAccess(bound, query.bindingKey, failure)
                failure
            }
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                fallback(request, spec, error)
            }
        }
        spec.validate(wire)
        try {
            coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { allowed ->
                val (repaired, storageAllowed) = repairDebtDirectRead(request, allowed)
                publish(repaired, spec, wire, storageAllowed)
            }
        } catch (error: DebtReadChanged) {
            if (!retryRepair || !request.canRetryRepair) throw error
            read(binding, scope, spec, retryRepair = false).getOrThrow()
        }
    }

    private suspend fun <T> fallback(request: DebtReadRequest, spec: DebtReadSpec<T>, error: Exception): ReadSnapshot<T> = mutex.withLock {
        val query = request.scope.row
        check(request.localGeneration == generation.get() && query.bindingKey !in retired)
        check(dao.debtDirectBarriers(query.bindingKey).isEmpty()) { "原往来提交结果仍待核对，请联网重新读取。" }
        check(dao.debtOutboxReadBarrier(query.bindingKey) == null) {
            "原往来提交已接受，读取仍待恢复。"
        }
        val denied = deniedResources(query.bindingKey)
        check(request.scope.publicId == null || request.scope.publicId !in denied) { "没有找到这笔欠款。" }
        val saved = dao.debtSnapshotIfCurrent(query, request.epoch) ?: throw error
        val stored = requireNotNull(saved.debtCachePayload())
        check(stored.epoch == request.epoch)
        val value = requireNotNull(spec.adapter.fromJson(stored.response))
        spec.validate(value)
        check(request.localGeneration == generation.get() && (dao.debtReadEpoch(query.bindingKey)?.toLong() ?: 0L) == request.epoch) {
            "往来已接受修改，请重新读取。"
        }
        check(dao.debtDirectBarriers(query.bindingKey).isEmpty() &&
            dao.debtOutboxReadBarrier(query.bindingKey) == null) {
            "原往来提交状态已变化，请重新读取。"
        }
        val currentDenied = deniedResources(query.bindingKey)
        check(request.scope.publicId == null || request.scope.publicId !in currentDenied) { "没有找到这笔欠款。" }
        ReadSnapshot(spec.project(value, currentDenied.keys), saved.fetchedAt, fromCache = true)
    }

    private suspend fun <T> publish(request: DebtReadRequest, spec: DebtReadSpec<T>, wire: T,
        cacheAllowed: Boolean): ReadSnapshot<T> = mutex.withLock {
        val query = request.scope.row
        val publicId = request.scope.publicId
        if (request.localGeneration != generation.get() || (dao.debtReadEpoch(query.bindingKey)?.toLong() ?: 0L) != request.epoch) throw DebtReadChanged()
        val denied = deniedResources(query.bindingKey)
        check(publicId == null || denied[publicId] == request.resourceFence) { "这笔往来的读取已失效。" }
        val restoring = restorableDebtResources(request, spec, wire, denied)
        val fresh = spec.project(wire, denied.keys - restoring.keys)
        val unpublished = dao.debtOutboxReadBarrier(query.bindingKey)?.responseJson
        check(request.unpublishedAcceptance == unpublished) { "原往来提交已接受，请重新读取。" }
        if (!cacheAllowed || unpublished != null) {
            return@withLock ReadSnapshot(fresh, Instant.now().toString(), fromCache = false)
        }
        val stored = DebtQueryCachePayload(request.epoch, request.ticket.sequence, spec.adapter.toJson(fresh), readOwner,
            spec.publicIds(fresh) + listOfNotNull(publicId))
        val incoming = AcceptedDebtQuery(query.copy(responseJson = debtQueryCacheAdapter.toJson(stored), fetchedAt = Instant.now().toString()),
            stored, request.ticket.generation)
        val key = "${query.bindingKey}|${query.kind}|${query.tag}"
        val previous = accepted[key]?.takeIf { it.stored.epoch == request.epoch && it.accessGeneration == request.ticket.generation } ?: try {
            dao.debtSnapshotIfCurrent(query, request.epoch)?.let { row -> row.debtCachePayload()?.let {
                AcceptedDebtQuery(row, it, request.ticket.generation) } }
        } catch (_: SQLiteException) { null }
        val selected = selectDebtRead(previous.takeIf { restoring.isEmpty() }, incoming, spec)
        accepted[key] = selected
        try {
            val restored = dao.saveDebtSnapshotIfCurrent(selected.query, request.epoch, restoring)
            retireRestoredDebtLists(accepted, localResourceDenials, request, restored)
            accepted[key] = selected
            retired.remove(query.bindingKey)
        } catch (_: SQLiteException) { /* A verified fresh GET remains usable. */ }
        val value = requireNotNull(spec.adapter.fromJson(selected.stored.response))
        val currentDenied = deniedResources(query.bindingKey)
        check(publicId?.let { currentDenied[it] in setOf(null, request.resourceFence) } != false) {
            "这笔往来的读取已失效。"
        }
        val stillDenied = currentDenied.filterNot { restoring[it.key] == it.value }.keys
        ReadSnapshot(spec.project(value, stillDenied), selected.query.fetchedAt, fromCache = selected !== incoming)
    }
    internal suspend fun rejectResource(binding: LogicalSessionBinding, publicId: String, failure: RepositoryException) {
        val query = debtScope(binding, "debt_resource_denial", publicId)
        val token = UUID.randomUUID().toString()
        val marked = try { coordinator.settingsStore.markDebtResourceCacheRetirement(query.bindingKey, publicId, token); true }
        catch (error: Exception) { if (error is CancellationException) throw error else false }
        if (!marked) localResourceDenials["${query.bindingKey}|$publicId"] = token
        resourceDenials.emit(DebtReadResourceDenial(binding, publicId, failure, resourceGeneration.incrementAndGet()))
        try {
            dao.retireDebtResourceCache(query.copy(responseJson = token, fetchedAt = Instant.now().toString()))
            localResourceDenials.remove("${query.bindingKey}|$publicId", token)
            coordinator.settingsStore.finishDebtResourceCacheRetirement(query.bindingKey, publicId, token)
        } catch (_: SQLiteException) { /* Preserve the original 404 and refuse this owner's stale resource. */ }
        catch (error: Exception) { if (error is CancellationException) throw error /* An uncleared marker is retried before cache use. */ }
    }

    private suspend fun deniedResources(bindingKey: String): Map<String, String> {
        repairDeferredDebtResourceRetirements(dao, coordinator.settingsStore, bindingKey)
        return dao.debtResourceDenials(bindingKey).associate { it.tag to it.responseJson } + localResourceDenials.entries
            .filter { it.key.startsWith("$bindingKey|") }.associate { it.key.removePrefix("$bindingKey|") to it.value } +
            coordinator.settingsStore.debtResourceCacheRetirements(bindingKey)
    }


}

private fun retireRestoredDebtLists(accepted: MutableMap<String, AcceptedDebtQuery>, localDenials: ConcurrentHashMap<String, String>,
    request: DebtReadRequest, restored: Set<String>) {
    if (restored.isNotEmpty()) {
        accepted.entries.removeAll { it.value.query.bindingKey == request.scope.row.bindingKey && it.value.query.kind == "debt_list" }
    }
    restored.forEach { localDenials.remove("${request.scope.row.bindingKey}|$it", request.resourceFences[it]) }
}

private fun <T> restorableDebtResources(request: DebtReadRequest, spec: DebtReadSpec<T>, wire: T, denied: Map<String, String>): Map<String, String> {
    val returned = spec.publicIds(wire) + listOfNotNull(request.scope.publicId)
    return denied.filter { it.key in returned && request.resourceFences[it.key] == it.value }
}

internal fun validateDebt(debt: DebtDto, binding: LogicalSessionBinding, publicId: String?, allowShell: Boolean) {
    require(debt.publicId.isNotBlank() && (publicId == null || debt.publicId == publicId) && debt.rowVersion > 0 &&
        (debt.ledgerId == binding.ledgerId || (allowShell && debt.ledgerId == null && debt.counterpartyType == "member" &&
            debt.viewerIsDebtor != null))) { "往来所属范围不匹配。" }
}

private suspend fun <T> fetchDebtNetwork(bound: BoundLedgerRequest, fetch: suspend ApiService.() -> T,
    refused: suspend (HttpException) -> RepositoryException): T = try { bound.call { fetch(it) } }
    catch (error: HttpException) { throw refused(error) }

private fun <T> selectDebtRead(previous: AcceptedDebtQuery?, incoming: AcceptedDebtQuery, spec: DebtReadSpec<T>): AcceptedDebtQuery {
    if (previous == null || previous.stored.epoch != incoming.stored.epoch) return incoming
    val old = try { spec.adapter.fromJson(previous.stored.response) } catch (_: IOException) { null }
        catch (_: JsonDataException) { null } ?: return incoming
    val fresh = requireNotNull(spec.adapter.fromJson(incoming.stored.response))
    return if (spec.isNewer(fresh, old) || (previous.stored.readOwner == incoming.stored.readOwner &&
        previous.stored.sequence > incoming.stored.sequence && !spec.isNewer(old, fresh))) previous else incoming
}

internal fun debtScope(binding: LogicalSessionBinding, kind: String, tag: String) = StatsProjectionCacheEntity(
    logicalBindingAdapter.toJson(binding), binding.ledgerId, kind, "", tag, "", "UTC", "", "")

/** Only the existing direct writer invokes this guard; the original command and key remain its own. */
internal suspend fun <T> DebtQueryReader.direct(binding: LogicalSessionBinding, publicId: String? = null, send: suspend () -> T): T {
    val bound = guard.bindExact(binding)
    val key = logicalBindingAdapter.toJson(binding)
    val token = UUID.randomUUID().toString()
    val activeKey = "$key|$token"
    activeDirect.add(activeKey)
    try {
        dao.saveStatsProjection(debtScope(binding, "debt_direct_barrier", token).copy(responseJson = token,
            fetchedAt = Instant.now().toString()))
        bound.requireStillActive()
        val result = try { send() } catch (error: HttpException) {
            val failure = NetworkErrorHandler({ binding.serverUrl }, "Debt").httpFailure(error)
            if (failure.httpStatusCode == 401) coordinator.rejectSnapshotAccess(bound, key, failure)
            if (failure.httpStatusCode == 404 && failure.errorCode == "debt_not_found" && publicId != null && bound.isStillActive()) {
                rejectResource(binding, publicId, failure)
            }
            if (error.code() in 400..499 && error.code() !in setOf(408, 429) && failure.errorCode != "idempotency_key_in_progress") {
                try { dao.clearDebtDirectBarriers(key, listOf(token)) } catch (_: SQLiteException) { /* Retry the read repair only. */ }
            }
            throw failure
        }
        generation.incrementAndGet()
        try {
            try { dao.settleDebtDirectReads(key, binding.ledgerId, listOf(token)) }
            catch (error: IllegalStateException) {
                // Explicit cache cleanup may already have retired this token and all its old projections.
                if (dao.debtDirectBarriers(key).any { it.tag == token }) throw error
                dao.invalidateDebtSnapshots(key, binding.ledgerId)
            }
        }
        catch (_: SQLiteException) { /* The durable token rejects old cache on reopen; the ACK remains accepted. */ }
        return result
    } finally { activeDirect.remove(activeKey) }
}

private suspend fun DebtQueryReader.repairDebtDirectRead(request: DebtReadRequest,
    cacheAllowed: Boolean): Pair<DebtReadRequest, Boolean> {
    val query = request.scope.row
    val tokens = dao.debtDirectBarriers(query.bindingKey).map { it.tag }.toSet()
    val publication = dao.debtOutboxReadBarrier(query.bindingKey)?.responseJson
    if (publication != request.unpublishedAcceptance || tokens != request.scope.directTokens) throw DebtReadChanged()
    val active = hasActiveDirect(query.bindingKey)
    check(!request.directWasActive || active) { "原往来提交状态已变化，请重新读取。" }
    if (!cacheAllowed || active) return request to false
    if (tokens.isEmpty() && publication == null) return request to true
    return try {
        dao.reconcileDebtReadBarriers(query.bindingKey, request.binding.ledgerId, request.epoch, tokens, publication)
        request.copy(epoch = request.epoch + 1, unpublishedAcceptance = null,
            scope = request.scope.copy(directTokens = emptySet())) to true
    } catch (_: SQLiteException) { request to false }
    catch (_: IllegalStateException) { throw DebtReadChanged() }
}

private fun DebtQueryReader.hasActiveDirect(bindingKey: String) = activeDirect.any { it.startsWith("$bindingKey|") }

    private suspend fun DebtQueryReader.listQuery(binding: LogicalSessionBinding, lens: String, fetch: suspend ApiService.() -> DebtListResponseDto) =
        read(binding, DebtQueryScope(debtScope(binding, "debt_list", lens)), DebtReadSpec(listAdapter, fetch,
            validate = { page ->
                require(page.items.map { it.publicId }.distinct().size == page.items.size)
                page.items.forEach { validateDebt(it, binding, null, allowShell = lens != DebtListLens.Ledger.name) }
            },
            isNewer = { old, incoming -> old.items.associateBy { it.publicId }.let { previous ->
                incoming.items.any { previous[it.publicId]?.rowVersion?.let { version -> version < it.rowVersion } == true }
            } },
            project = { page, denied -> page.copy(items = page.items.filterNot { it.publicId in denied }) },
            publicIds = { page -> page.items.mapTo(mutableSetOf()) { it.publicId } }))
