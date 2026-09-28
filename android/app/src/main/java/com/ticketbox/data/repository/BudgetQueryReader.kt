package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.JsonDataException
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.BudgetReadState
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.BudgetMonthly
import java.io.IOException
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

private data class AcceptedBudgetRead(val wire: BudgetMonthlyDto, val query: StatsProjectionCacheEntity,
    val ticket: SnapshotReadTicket, val saveGeneration: Long, val readState: BudgetReadState) {
    fun isNewerThan(other: AcceptedBudgetRead): Boolean {
        val revision = wire.rowVersion?.takeIf { it > 0 }
        val otherRevision = other.wire.rowVersion?.takeIf { it > 0 }
        return if (revision != null && otherRevision != null && revision != otherRevision) revision > otherRevision
            else ticket.sequence > other.ticket.sequence
    }
}

/** BudgetRepository's complete server query projection; command receipts never seed it. */
internal class BudgetQueryReader(
    apiProvider: ApiServiceProvider,
    private val dao: ExpenseDao,
    private val coordinator: LocalLedgerSessionCoordinator,
    private val outbox: OutboxRepository,
) {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "Budget",
        statusMessages = mapOf(404 to "预算不存在。"))
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val adapter = moshi.adapter(BudgetMonthlyDto::class.java)
    private val bindingAdapter = moshi.adapter(LogicalSessionBinding::class.java)
    private val mutex = Mutex()
    private val latestAcceptedReads = mutableMapOf<String, AcceptedBudgetRead>()
    private val minimumRevisions = mutableMapOf<String, Long>()
    // Unconfigured reads have no revision; only responses started after acceptance may replace the saved budget.
    private val saveGenerations = mutableMapOf<String, Long>()
    private val readProtection = BudgetReadProtection(dao)
    val history = BudgetHistoryQueries(apiProvider, dao, coordinator, ::recoverReadRefresh, readProtection)

    suspend fun <T> directRestore(binding: LogicalSessionBinding, month: String, send: suspend () -> T): T {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val bound = guard.bindExact(binding)
        bound.requireStillActive()
        return try { readProtection.restore(binding, clean, send) }
        catch (error: HttpException) {
            if (error.code() == 401) coordinator.rejectSnapshotAccess(bound, bindingAdapter.toJson(binding), errors.httpFailure(error))
            throw error
        }
    }

    suspend fun invalidate(row: OutboxRow, acceptedRevision: Long?) {
        val binding = requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        require(row.ledgerId == binding.ledgerId && row.ownerKey == binding.ownerKey &&
            canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
            "账本已切换，请重新操作。"
        }
        val bindingKey = bindingAdapter.toJson(binding)
        val month = row.targetId.removePrefix("monthly_budget:")
        mutex.withLock {
            val monthKey = "$bindingKey|$month"
            // A repair marker is written only after the original OCC + 1 result was verified.
            val minimum = maxOf(minimumRevisions[monthKey] ?: 0L, acceptedRevision ?: (row.expectedRowVersion + 1))
            minimumRevisions[monthKey] = minimum
            saveGenerations[monthKey] = (saveGenerations[monthKey] ?: 0L) + 1
            history.invalidate(bindingKey, month, minimum, retireUnconditionally = acceptedRevision == null)
            dao.budgetSnapshotsForMonth(bindingKey, month).forEach { saved ->
                val cached = readCached(saved)
                if (acceptedRevision == null || cached == null || (cached.rowVersion ?: 0L) < minimum) dao.deleteStatsProjection(saved)
            }
        }
    }

    suspend fun read(month: String, timezone: String, expectedBinding: LogicalSessionBinding?,
        freshOnly: Boolean = false): Result<ReadSnapshot<BudgetMonthly>> = errors.safeCall {
        val cleanMonth = validatedBudgetMonth(month).getOrThrow()
        ZoneId.of(timezone)
        val binding = expectedBinding ?: requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        val bound = guard.bindExact(binding)
        recoverReadRefresh(bound, cleanMonth)
        val bindingKey = bindingAdapter.toJson(binding)
        val ticket = coordinator.beginSnapshotRead()
        val readState = readProtection.beginRead(bindingKey, cleanMonth)
        val queryScope = StatsProjectionCacheEntity(bindingKey, binding.ledgerId, "budget", cleanMonth, "", "", timezone, "", "")
        val saveGeneration = mutex.withLock { saveGenerations["$bindingKey|$cleanMonth"] ?: 0L }
        val wire = try {
            bound.call { it.monthlyBudget(cleanMonth, timezone) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, bindingKey, failure)
            throw failure
        } catch (error: Exception) {
            if (freshOnly || !error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                mutex.withLock {
                    val saved = dao.budgetSnapshotIfCurrent(queryScope, readState, requireSettled = true)
                        ?: throw error
                    val cached = requireNotNull(readCached(saved))
                    validate(cached, binding.ledgerId, cleanMonth)
                    requireAcceptedRevision(bindingKey, cached)
                    ReadSnapshot(cached.toDomain(), saved.fetchedAt, fromCache = true)
                }
            }
        }
        validate(wire, binding.ledgerId, cleanMonth)
        val query = queryScope.copy(responseJson = adapter.toJson(wire), fetchedAt = Instant.now().toString())
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            mutex.withLock {
                readProtection.requireCurrent(bindingKey, cleanMonth, readState)
                if (!cacheAllowed) {
                    requireAcceptedRevision(bindingKey, wire, saveGeneration)
                    return@withLock ReadSnapshot(wire.toDomain(), query.fetchedAt, fromCache = false)
                }
                val saved = try { dao.budgetSnapshotIfCurrent(queryScope, readState, requireSettled = false) }
                    catch (_: SQLiteException) { null }
                val snapshot = acceptWire(wire, query, ticket, saveGeneration, saved, readState)
                if (freshOnly) {
                    // Room keeps its newer query; this independent GET still supplies a fresh result.
                    ReadSnapshot(wire.toDomain(), query.fetchedAt, fromCache = false)
                } else snapshot
            }
        }
    }

    private suspend fun recoverReadRefresh(bound: BoundLedgerRequest, month: String) {
        // The binding lease covers cleanup and compare-clear; cleanup never enters the coordinator.
        outbox.recoverBudgetReadRefresh(bound, month) { row ->
            val receipt = try { adapter.fromJson(requireNotNull(row.receiptJson)) }
                catch (_: JsonDataException) { null } catch (_: IOException) { null }
            val revision = receipt?.takeIf { it.configured && it.ledgerId == row.ledgerId && it.month == month &&
                it.rowVersion == row.expectedRowVersion + 1 }?.rowVersion
            // Preserve the accepted row and its original bytes; an unreadable receipt only retires query caches.
            invalidate(row, revision)
        }
    }

    private suspend fun acceptWire(wire: BudgetMonthlyDto, query: StatsProjectionCacheEntity,
        ticket: SnapshotReadTicket, saveGeneration: Long, saved: StatsProjectionCacheEntity?, readState: BudgetReadState): ReadSnapshot<BudgetMonthly> {
        requireAcceptedRevision(query.bindingKey, wire, saveGeneration)
        val cacheKey = "${query.bindingKey}|${wire.month}|${query.timezone}"
        val incoming = AcceptedBudgetRead(wire, query, ticket, saveGeneration, readState)
        val previous = latestAcceptedReads[cacheKey]?.takeIf {
            it.ticket.generation == ticket.generation && it.readState == readState && acceptsRevision(query.bindingKey, it.wire, it.saveGeneration)
        }
        var selected = previous?.takeIf { it.isNewerThan(incoming) } ?: incoming
        val cached = saved?.let(::readCached)
        if (saved != null && cached != null) {
            validate(cached, query.ledgerId, wire.month)
            val savedTicket = ticket.copy(sequence = previous?.takeIf { it.query == saved }?.ticket?.sequence ?: 0L)
            val stored = AcceptedBudgetRead(cached, saved, savedTicket, saveGeneration, readState)
            if (stored.isNewerThan(selected)) selected = stored
        }
        // Network acceptance survives SQLite publication failure and precedes the next independent response.
        latestAcceptedReads[cacheKey] = selected
        val persisted = selected.query == saved || readProtection.publish(selected.query, readState)
        return ReadSnapshot(selected.wire.toDomain(), selected.query.fetchedAt, fromCache = persisted && selected !== incoming)
    }

    /** Rebuildable query rows may be discarded; command acceptance is still verified by the dispatcher. */
    private fun readCached(saved: StatsProjectionCacheEntity): BudgetMonthlyDto? = try {
        adapter.fromJson(saved.responseJson)?.takeIf { it.ledgerId == saved.ledgerId && it.month == saved.month }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

    private fun requireAcceptedRevision(bindingKey: String, wire: BudgetMonthlyDto, saveGeneration: Long? = null) {
        check(acceptsRevision(bindingKey, wire, saveGeneration)) {
            "预算已保存更新，请重新读取。"
        }
    }

    private fun acceptsRevision(bindingKey: String, wire: BudgetMonthlyDto, saveGeneration: Long? = null): Boolean {
        val monthKey = "$bindingKey|${wire.month}"
        val revision = wire.rowVersion?.takeIf { it > 0 }
        return if (revision != null) revision >= (minimumRevisions[monthKey] ?: 0L)
            else saveGeneration == null || saveGeneration == (saveGenerations[monthKey] ?: 0L)
    }

    private fun validate(wire: BudgetMonthlyDto, ledgerId: String, month: String) {
        require(wire.ledgerId == ledgerId && wire.month == month) { "预算所属账本或月份不匹配。" }
    }
}
