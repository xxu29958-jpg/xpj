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
) {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "Budget",
        statusMessages = mapOf(404 to "预算不存在。"))
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val adapter = moshi.adapter(BudgetMonthlyDto::class.java)
    private val bindingAdapter = moshi.adapter(LogicalSessionBinding::class.java)
    private val mutex = Mutex()
    private val latestRequests = mutableMapOf<String, Long>()

    suspend fun invalidate(row: OutboxRow) {
        val binding = requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        require(row.ledgerId == binding.ledgerId && row.ownerKey == binding.ownerKey &&
            canonicalServerOriginOrNull(row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl)) {
            "账本已切换，请重新操作。"
        }
        val bindingKey = bindingAdapter.toJson(binding)
        val month = row.targetId.removePrefix("monthly_budget:")
        mutex.withLock {
            latestRequests.keys.removeAll { it.startsWith("$bindingKey|$month|") }
            dao.clearBudgetSnapshotsForMonth(bindingKey, month)
        }
    }

    suspend fun read(month: String, timezone: String, expectedBinding: LogicalSessionBinding?,
        freshOnly: Boolean = false): Result<ReadSnapshot<BudgetMonthly>> = errors.safeCall {
        val cleanMonth = validatedBudgetMonth(month).getOrThrow()
        ZoneId.of(timezone)
        val binding = expectedBinding ?: requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        val bound = guard.bindExact(binding)
        val bindingKey = bindingAdapter.toJson(binding)
        val ticket = coordinator.beginSnapshotRead()
        val cacheKey = "$bindingKey|$cleanMonth|$timezone"
        mutex.withLock { latestRequests[cacheKey] = ticket.sequence }
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
                    requireLatest(cacheKey, ticket)
                    val saved = dao.statsProjections(bindingKey, "budget", cleanMonth, "", timezone).singleOrNull()
                        ?: throw error
                    val cached = requireNotNull(adapter.fromJson(saved.responseJson))
                    validate(cached, binding, cleanMonth)
                    ReadSnapshot(cached.toDomain(), saved.fetchedAt, fromCache = true)
                }
            }
        }
        validate(wire, binding, cleanMonth)
        coordinator.acceptSnapshotRead(ticket, bound) {
            mutex.withLock {
                requireLatest(cacheKey, ticket)
                val fetchedAt = Instant.now().toString()
                dao.saveStatsProjection(StatsProjectionCacheEntity(bindingKey, binding.ledgerId, "budget",
                    cleanMonth, "", "", timezone, adapter.toJson(wire), fetchedAt))
                ReadSnapshot(wire.toDomain(), fetchedAt, fromCache = false)
            }
        }
    }

    private fun requireLatest(cacheKey: String, ticket: SnapshotReadTicket) {
        check(latestRequests[cacheKey] == ticket.sequence) { "预算已有更新的读取，请重新读取。" }
    }

    private fun validate(wire: BudgetMonthlyDto, binding: LogicalSessionBinding, month: String) {
        require(wire.ledgerId == binding.ledgerId && wire.month == month) { "预算所属账本或月份不匹配。" }
    }
}
