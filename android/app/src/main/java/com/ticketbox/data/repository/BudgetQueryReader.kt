package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.BudgetMonthly
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

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
    private val latestAcceptedReads = mutableMapOf<String, Long>()
    private val minimumRevisions = mutableMapOf<String, Long>()
    // Unconfigured reads have no revision; only responses started after acceptance may replace the saved budget.
    private val saveGenerations = mutableMapOf<String, Long>()

    suspend fun invalidate(row: OutboxRow, acceptedRevision: Long) {
        val binding = requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        require(row.ledgerId == binding.ledgerId && row.ownerKey == binding.ownerKey &&
            canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
            "账本已切换，请重新操作。"
        }
        val bindingKey = bindingAdapter.toJson(binding)
        val month = row.targetId.removePrefix("monthly_budget:")
        mutex.withLock {
            val monthKey = "$bindingKey|$month"
            val minimum = maxOf(minimumRevisions[monthKey] ?: 0L, acceptedRevision)
            minimumRevisions[monthKey] = minimum
            saveGenerations[monthKey] = (saveGenerations[monthKey] ?: 0L) + 1
            dao.budgetSnapshotsForMonth(bindingKey, month).forEach { saved ->
                val revision = adapter.fromJson(saved.responseJson)?.rowVersion ?: 0L
                if (revision < minimum) dao.deleteStatsProjection(saved)
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
        val saveGeneration = mutex.withLock { saveGenerations["$bindingKey|$cleanMonth"] ?: 0L }
        val wire = try {
            bound.call { it.monthlyBudget(cleanMonth, timezone) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, bindingKey, failure)
            throw failure
        } catch (error: Exception) {
            if (freshOnly || !error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound) {
                mutex.withLock {
                    val saved = dao.statsProjections(bindingKey, "budget", cleanMonth, "", timezone).singleOrNull()
                        ?: throw error
                    val cached = requireNotNull(adapter.fromJson(saved.responseJson))
                    validate(cached, binding, cleanMonth)
                    requireAcceptedRevision(bindingKey, cached)
                    ReadSnapshot(cached.toDomain(), saved.fetchedAt, fromCache = true)
                }
            }
        }
        validate(wire, binding, cleanMonth)
        coordinator.acceptSnapshotRead(ticket, bound) {
            mutex.withLock {
                acceptWire(wire, binding, timezone, ticket, saveGeneration).also {
                    check(!freshOnly || !it.fromCache) { "预算已有更新的读取，请重新读取。" }
                }
            }
        }
    }

    private suspend fun recoverReadRefresh(bound: BoundLedgerRequest, month: String) {
        // The binding lease covers cleanup and compare-clear; cleanup never enters the coordinator.
        outbox.recoverBudgetReadRefresh(bound, month) { row ->
            val receipt = requireNotNull(adapter.fromJson(requireNotNull(row.receiptJson)))
            require(receipt.configured && receipt.ledgerId == row.ledgerId && receipt.month == month)
            val revision = requireNotNull(receipt.rowVersion).also { require(it > 0) }
            invalidate(row, revision)
        }
    }

    private suspend fun acceptWire(wire: BudgetMonthlyDto, binding: LogicalSessionBinding,
        timezone: String, ticket: SnapshotReadTicket, saveGeneration: Long): ReadSnapshot<BudgetMonthly> {
        val bindingKey = bindingAdapter.toJson(binding)
        requireAcceptedRevision(bindingKey, wire, saveGeneration)
        val cacheKey = "$bindingKey|${wire.month}|$timezone"
        val saved = dao.statsProjections(bindingKey, "budget", wire.month, "", timezone).singleOrNull()
        if (saved != null) {
            val cached = requireNotNull(adapter.fromJson(saved.responseJson))
            validate(cached, binding, wire.month)
            val savedRevision = cached.rowVersion?.takeIf { it > 0 }
            val wireRevision = wire.rowVersion?.takeIf { it > 0 }
            val newerRead = (latestAcceptedReads[cacheKey] ?: 0L) > ticket.sequence
            val newerRevision = savedRevision != null && wireRevision != null && savedRevision > wireRevision
            val useSequence = savedRevision == null || wireRevision == null || savedRevision == wireRevision
            if (newerRevision || useSequence && newerRead) {
                return ReadSnapshot(cached.toDomain(), saved.fetchedAt, fromCache = true)
            }
        }
        val fetchedAt = Instant.now().toString()
        dao.saveStatsProjection(StatsProjectionCacheEntity(bindingKey, binding.ledgerId, "budget",
            wire.month, "", "", timezone, adapter.toJson(wire), fetchedAt))
        latestAcceptedReads[cacheKey] = ticket.sequence
        return ReadSnapshot(wire.toDomain(), fetchedAt, fromCache = false)
    }

    private fun requireAcceptedRevision(bindingKey: String, wire: BudgetMonthlyDto, saveGeneration: Long? = null) {
        val monthKey = "$bindingKey|${wire.month}"
        val revision = wire.rowVersion?.takeIf { it > 0 }
        val allowed = if (revision != null) revision >= (minimumRevisions[monthKey] ?: 0L)
            else saveGeneration == null || saveGeneration == (saveGenerations[monthKey] ?: 0L)
        check(allowed) {
            "预算已保存更新，请重新读取。"
        }
    }

    private fun validate(wire: BudgetMonthlyDto, binding: LogicalSessionBinding, month: String) {
        require(wire.ledgerId == binding.ledgerId && wire.month == month) { "预算所属账本或月份不匹配。" }
    }
}
