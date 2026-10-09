package com.ticketbox.data.repository

import android.database.sqlite.SQLiteException
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.GoalQueryCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalHistoryResponseDto
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalHistoryPage
import java.time.Instant
import java.time.YearMonth
import java.time.ZoneId
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

/** ReportsRepository's Goal query implementation; it never consumes command receipts. */
internal class GoalQueryReader(
    apiProvider: ApiServiceProvider,
    private val dao: ExpenseDao,
    private val coordinator: LocalLedgerSessionCoordinator,
) {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "Goals")
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val goalsAdapter by lazy { moshi.adapter<List<GoalDto>>(Types.newParameterizedType(List::class.java, GoalDto::class.java)) }
    private val bindingAdapter by lazy { moshi.adapter(LogicalSessionBinding::class.java) }
    private val historyAdapter by lazy { moshi.adapter(GoalHistoryResponseDto::class.java) }
    private val mutex = Mutex()
    private val latestRequests = mutableMapOf<String, Long>()
    private val latestDetails = mutableMapOf<String, Long>()

    /** A successful command retires read projections, without treating its receipt as a new query. */
    suspend fun invalidate(binding: LogicalSessionBinding) {
        val bindingKey = bindingAdapter.toJson(binding)
        mutex.withLock {
            latestRequests.keys.removeAll { it.startsWith("$bindingKey|") }
            latestDetails.keys.removeAll { it.startsWith("$bindingKey|") }
            dao.clearGoalSnapshotsForBinding(bindingKey)
        }
    }

    suspend fun goals(month: String?, includeArchived: Boolean, expectedBinding: LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> =
        read(GoalQuery("spending_limit", month, includeArchived), expectedBinding, timezone) { api, query ->
            api.goals(query.month, query.includeArchived, timezone = timezone).items
        }

    suspend fun debtGoals(includeArchived: Boolean, expectedBinding: LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<List<Goal>>> =
        read(GoalQuery("debt_repayment", includeArchived = includeArchived), expectedBinding, timezone) { api, query ->
            api.goals(goalType = "debt_repayment", includeArchived = query.includeArchived, timezone = timezone).items
        }

    suspend fun goal(publicId: String, expectedBinding: LogicalSessionBinding?, timezone: String): Result<ReadSnapshot<Goal>> =
        read(GoalQuery("detail", publicId = publicId.trim()), expectedBinding, timezone) { api, query ->
            listOf(api.goal(requireNotNull(query.publicId), timezone))
        }.map { ReadSnapshot(it.value.single(), it.fetchedAt, it.fromCache) }

    suspend fun history(publicId: String, beforeVersion: Long?, binding: LogicalSessionBinding): Result<ReadSnapshot<GoalHistoryPage>> = errors.safeCall {
        require(publicId.isNotBlank() && (beforeVersion == null || beforeVersion > 0)) { "目标历史范围不正确。" }
        val bound = guard.bindExact(binding)
        val bindingKey = bindingAdapter.toJson(binding)
        val queryKey = "history:$publicId:50:$beforeVersion"
        val cacheKey = "$bindingKey|UTC|$queryKey"
        val ticket = coordinator.beginSnapshotRead()
        mutex.withLock { latestRequests[cacheKey] = ticket.sequence }
        val wire = try {
            bound.call { it.goalHistory(publicId, 50, beforeVersion) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, bindingKey, failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                mutex.withLock {
                    requireLatest(cacheKey, ticket)
                    val saved = dao.goalSnapshot(bindingKey, "UTC", queryKey) ?: throw error
                    val page = requireNotNull(historyAdapter.fromJson(saved.responseJson))
                    page.validateHistory(publicId, beforeVersion, binding)
                    ReadSnapshot(page.toDomain(), saved.fetchedAt, fromCache = true)
                }
            }
        }
        wire.validateHistory(publicId, beforeVersion, binding)
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            mutex.withLock {
                requireLatest(cacheKey, ticket)
                val fetchedAt = Instant.now().toString()
                if (cacheAllowed) {
                    try {
                        dao.saveGoalSnapshots(listOf(GoalQueryCacheEntity(bindingKey, binding.ledgerId,
                            "UTC", queryKey, historyAdapter.toJson(wire), fetchedAt)))
                    } catch (_: SQLiteException) {
                        // Rebuildable storage failure cannot erase this authorized fresh GET.
                    }
                }
                ReadSnapshot(wire.toDomain(), fetchedAt, fromCache = false)
            }
        }
    }

    private suspend fun read(
        requested: GoalQuery,
        expectedBinding: LogicalSessionBinding?,
        timezone: String,
        fetch: suspend (ApiService, GoalQuery) -> List<GoalDto>,
    ): Result<ReadSnapshot<List<Goal>>> = errors.safeCall {
        val query = requested.validated(timezone)
        val binding = expectedBinding ?: requireNotNull(guard.captureLogicalBinding()) { "请重新绑定账本。" }
        val bound = guard.bindExact(binding)
        val bindingKey = bindingAdapter.toJson(binding)
        val ticket = coordinator.beginSnapshotRead()
        val cacheKey = "$bindingKey|$timezone|${query.key}"
        mutex.withLock { latestRequests[cacheKey] = ticket.sequence }
        val wire = try {
            bound.call { fetch(it, query) }
        } catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, bindingKey, failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                mutex.withLock {
                    requireLatest(cacheKey, ticket)
                    val saved = dao.goalSnapshot(bindingKey, timezone, query.key) ?: throw error
                    val rows = requireNotNull(goalsAdapter.fromJson(saved.responseJson))
                    validateGoals(rows, query, binding)
                    ReadSnapshot(rows.map { it.toDomain() }, saved.fetchedAt, fromCache = true)
                }
            }
        }
        validateGoals(wire, query, binding)
        val values = wire.map { it.toDomain() }
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            mutex.withLock {
                requireLatest(cacheKey, ticket)
                val detailKeys = wire.map { "$bindingKey|$timezone|detail:${it.publicId}" }
                check(detailKeys.all { ticket.sequence >= (latestRequests[it] ?: 0) && ticket.sequence >= (latestDetails[it] ?: 0) }) {
                    "目标已有更新的读取，请重新读取。"
                }
                val fetchedAt = Instant.now().toString()
                val snapshot = GoalQueryCacheEntity(bindingKey, binding.ledgerId, timezone, query.key,
                    goalsAdapter.toJson(wire), fetchedAt)
                val details = if (query.publicId != null) emptyList() else wire.map { goal ->
                    snapshot.copy(queryKey = "detail:${goal.publicId}", responseJson = goalsAdapter.toJson(listOf(goal)))
                }
                if (cacheAllowed) dao.saveGoalSnapshots(listOf(snapshot) + details)
                detailKeys.forEach { latestDetails[it] = ticket.sequence }
                ReadSnapshot(values, fetchedAt, fromCache = false)
            }
        }
    }

    private fun requireLatest(cacheKey: String, ticket: SnapshotReadTicket) {
        check(latestRequests[cacheKey] == ticket.sequence) { "目标已有更新的读取，请重新读取。" }
    }
}

private fun GoalHistoryResponseDto.validateHistory(id: String, before: Long?, binding: LogicalSessionBinding) {
    require(publicId == id && ledgerId == binding.ledgerId) { "目标历史所属账本不匹配。" }
    val versions = items.map { it.rowVersion }
    require(items.size <= 50 && versions.all { it > 0 && (before == null || it < before) } &&
        versions.zipWithNext().all { (a, b) -> a > b }) { "目标历史顺序不正确。" }
    require(nextBeforeVersion == null || versions.lastOrNull() == nextBeforeVersion) { "目标历史分页不正确。" }
    items.forEach { it.validateDefinition() }
}

private fun com.ticketbox.data.remote.dto.GoalRevisionDto.validateDefinition() {
    Instant.parse(recordedAt)
    require(changeKind in setOf("baseline", "create", "edit", "archive", "restore")) { "目标历史变更无法识别。" }
    require(snapshot.goalType == "spending_limit" && snapshot.period == "monthly" && snapshot.name.isNotBlank() &&
        snapshot.status in setOf("active", "archived") && (snapshot.targetAmountCents ?: 0) > 0) { "目标历史定义不正确。" }
    YearMonth.parse(requireNotNull(snapshot.month))
    require((changeKind != "archive" || snapshot.status == "archived") &&
        (changeKind != "restore" || snapshot.status == "active")) { "目标历史状态不正确。" }
}

private data class GoalQuery(
    val type: String,
    val month: String? = null,
    val includeArchived: Boolean = false,
    val publicId: String? = null,
) {
    val key: String get() = publicId?.let { "detail:$it" } ?: "list:$type:$month:$includeArchived"

    fun validated(timezone: String): GoalQuery {
        ZoneId.of(timezone)
        if (type == "detail") require(!publicId.isNullOrBlank()) { "目标编号不能为空。" }
        return if (type == "spending_limit") copy(month = month?.trim()?.takeIf { it.isNotEmpty() }
            ?.let { YearMonth.parse(it).toString() }) else this
    }
}

private fun validateGoals(rows: List<GoalDto>, query: GoalQuery, binding: LogicalSessionBinding) {
    require(rows.map { it.publicId }.distinct().size == rows.size) { "目标列表包含重复记录。" }
    if (query.publicId != null) require(rows.size == 1 && rows.single().publicId == query.publicId) { "目标读取不匹配。" }
    rows.forEach { goal ->
        require(goal.ledgerId == binding.ledgerId && goal.publicId.isNotBlank() && goal.rowVersion > 0) { "目标所属账本不匹配。" }
        require(goal.goalType in setOf("spending_limit", "debt_repayment")) { "目标类型无法识别。" }
        if (query.publicId == null) {
            require(goal.goalType == query.type && (query.includeArchived || goal.status != "archived")) { "目标列表范围不匹配。" }
            if (query.type == "spending_limit" && query.month != null) require(goal.month == query.month) { "目标月份不匹配。" }
        }
    }
}
