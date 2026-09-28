package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.BudgetReadState
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.dto.BudgetHistoryDto
import com.ticketbox.domain.model.BudgetHistoryPage
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

private data class AcceptedBudgetHistory(val page: BudgetHistoryDto, val query: StatsProjectionCacheEntity,
    val ticket: SnapshotReadTicket, val readState: BudgetReadState) {
    fun precedes(other: AcceptedBudgetHistory): Boolean {
        val revision = page.items.firstOrNull()?.rowVersion ?: 0L
        val otherRevision = other.page.items.firstOrNull()?.rowVersion ?: 0L
        return revision < otherRevision || (revision == otherRevision && ticket.sequence < other.ticket.sequence)
    }
}

/** BudgetQueryReader's history pages share its Room store, access coordinator and accepted-save invalidation. */
internal class BudgetHistoryQueries(
    apiProvider: ApiServiceProvider,
    private val dao: ExpenseDao,
    private val coordinator: LocalLedgerSessionCoordinator,
    private val prepareRead: suspend (BoundLedgerRequest, String) -> Unit,
    private val readProtection: BudgetReadProtection,
) : BudgetHistoryReader {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "BudgetHistory")
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(BudgetHistoryDto::class.java)
    private val mutex = Mutex()
    private val accepted = mutableMapOf<String, AcceptedBudgetHistory>()
    private val minimumRevisions = mutableMapOf<String, Long>()

    suspend fun invalidate(bindingKey: String, month: String, minimumRevision: Long, retireUnconditionally: Boolean) = mutex.withLock {
        minimumRevisions["$bindingKey|$month"] = maxOf(minimumRevisions["$bindingKey|$month"] ?: 0L, minimumRevision)
        val saved = dao.statsProjections(bindingKey, "budget_history", month, "", "UTC").singleOrNull()
        val revision = saved?.let(::decode)?.items?.firstOrNull()?.rowVersion ?: 0L
        if (saved != null && (retireUnconditionally || revision < minimumRevision)) dao.deleteStatsProjection(saved)
    }

    override suspend fun history(binding: LogicalSessionBinding, month: String, beforeVersion: Long?): Result<ReadSnapshot<BudgetHistoryPage>> =
        errors.safeCall {
            val before = beforeVersion
            val clean = validatedBudgetMonth(month).getOrThrow()
            require(before == null || before > 0)
            val bound = guard.bindExact(binding)
            prepareRead(bound, clean)
            val ticket = coordinator.beginSnapshotRead()
            val key = logicalBindingAdapter.toJson(binding)
            val readState = readProtection.beginRead(key, clean)
            val queryScope = StatsProjectionCacheEntity(key, binding.ledgerId, "budget_history", clean,
                before?.toString().orEmpty(), "", "UTC", "", "")
            val page = try {
                bound.call { it.budgetHistory(clean, before) }
            } catch (error: HttpException) {
                val failure = errors.httpFailure(error)
                coordinator.rejectSnapshotAccess(bound, key, failure)
                throw failure
            } catch (error: Exception) {
                if (!error.isReadTransportUnavailable()) throw error
                return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                    mutex.withLock {
                        val saved = dao.budgetSnapshotIfCurrent(queryScope, readState, requireSettled = true) ?: throw error
                        val cached = requireNotNull(decode(saved)) { "已读预算历史暂时无法恢复，请联网重新读取。" }
                        cached.validateHistory(binding.ledgerId, clean, before)
                        requireCurrent(key, cached, before)
                        ReadSnapshot(cached.toDomain(), saved.fetchedAt, fromCache = true)
                    }
                }
            }
            page.validateHistory(binding.ledgerId, clean, before)
            val query = queryScope.copy(responseJson = adapter.toJson(page), fetchedAt = Instant.now().toString())
            coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
                mutex.withLock {
                    readProtection.requireCurrent(key, clean, readState)
                    if (!cacheAllowed) {
                        requireCurrent(key, page, before)
                        return@withLock ReadSnapshot(page.toDomain(), query.fetchedAt, fromCache = false)
                    }
                    publish(AcceptedBudgetHistory(page, query, ticket, readState), before)
                }
            }
        }

    private suspend fun publish(incoming: AcceptedBudgetHistory, before: Long?): ReadSnapshot<BudgetHistoryPage> {
        val query = incoming.query
        val cacheKey = "${query.bindingKey}|${query.month}|${query.tag}"
        val previous = accepted[cacheKey]?.takeIf { it.ticket.generation == incoming.ticket.generation && it.readState == incoming.readState }
        var selected = previous?.takeUnless { it.precedes(incoming) } ?: incoming
        val saved = try { dao.budgetSnapshotIfCurrent(query, incoming.readState, requireSettled = false) }
            catch (_: SQLiteException) { null }
        val cached = saved?.let(::decode)?.takeIf {
            runCatching { it.validateHistory(query.ledgerId, query.month, before) }.isSuccess
        }
        if (saved != null && cached != null) {
            val stored = AcceptedBudgetHistory(cached, saved, incoming.ticket.copy(sequence = 0L), incoming.readState)
            if (selected.precedes(stored)) selected = stored
        }
        requireCurrent(query.bindingKey, selected.page, before)
        accepted[cacheKey] = selected
        if (selected.query != saved) {
            readProtection.publish(selected.query, incoming.readState)
        }
        return ReadSnapshot(selected.page.toDomain(), selected.query.fetchedAt, fromCache = selected.ticket.sequence == 0L)
    }

    private fun requireCurrent(bindingKey: String, page: BudgetHistoryDto, before: Long?) {
        if (before != null) return // Immutable older revisions remain valid after a later save.
        check((page.items.firstOrNull()?.rowVersion ?: 0L) >= (minimumRevisions["$bindingKey|${page.month}"] ?: 0L)) {
            "预算已保存更新，请重新读取修改记录。"
        }
    }

    private fun decode(saved: StatsProjectionCacheEntity): BudgetHistoryDto? = try {
        adapter.fromJson(saved.responseJson)?.takeIf { it.ledgerId == saved.ledgerId && it.month == saved.month }
    } catch (_: JsonDataException) { null } catch (_: IOException) { null }
}

private fun BudgetHistoryDto.validateHistory(ledger: String, expectedMonth: String, before: Long?) {
    require(ledgerId == ledger && month == expectedMonth) { "预算历史所属账本或月份不匹配。" }
    val versions = items.map { it.rowVersion }
    require(items.size <= 50 && versions.all { it > 0 && (before == null || it < before) } &&
        versions.zipWithNext().all { (a, b) -> a > b }) { "预算历史顺序不正确。" }
    require(nextBeforeVersion == null || versions.lastOrNull() == nextBeforeVersion) { "预算历史分页不正确。" }
    items.forEach {
        Instant.parse(it.recordedAt)
        require(it.changeKind in setOf("baseline", "create", "edit", "archive", "restore")) { "预算历史变更无法识别。" }
        require(it.snapshot.totalAmountCents >= 0 && it.snapshot.nonMonthlyAmountCents >= 0 &&
            it.snapshot.categoryBudgets.all { category -> category.category.isNotBlank() && category.amountCents >= 0 }) {
            "预算历史安排无法确认。"
        }
    }
}
