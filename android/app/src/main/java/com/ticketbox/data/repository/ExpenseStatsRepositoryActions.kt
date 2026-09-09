package com.ticketbox.data.repository

import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import com.squareup.moshi.Moshi
import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import java.time.Instant
import java.time.YearMonth
import java.time.ZoneId

private enum class StatsProjectionKind(val storageKey: String) { Monthly("monthly"), Lifestyle("lifestyle") }

internal class ExpenseStatsRepositoryActions(
    private val core: ExpenseRepositoryCore,
    private val ledgerActions: LedgerActions,
) : StatsActions {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val monthlyAdapter = moshi.adapter(MonthlyStatsDto::class.java)
    private val lifestyleAdapter = moshi.adapter(LifestyleStatsDto::class.java)
    private val bindingAdapter = moshi.adapter(LogicalSessionBinding::class.java)
    private val cacheMutex = Mutex()
    private val latestReads = mutableMapOf<StatsProjectionKind, Any>()

    override fun observeStatsBinding(): Flow<LogicalSessionBinding?> =
        core.apiProvider.observeActiveLedgerAccess().map { it?.binding }.distinctUntilChanged()

    override fun statsBinding(): LogicalSessionBinding? = core.ledgerRequestGuard.captureLogicalBinding()

    override fun lastUploadAt(): String? =
        core.apiProvider.currentLedgerId()
            ?.let(core.settingsStore::lastUploadAtForLedger)

    override suspend fun months(): Result<List<String>> = ledgerActions.months()

    override suspend fun tags(): Result<List<String>> = ledgerActions.tags()

    override suspend fun monthlyStats(query: StatsQuery): Result<StatsRead<MonthlyStats>> =
        read(query, StatsProjectionKind.Monthly, monthlyAdapter, { dto -> dto.month to dto.homeCurrencyCode }, MonthlyStatsDto::toDomain) { api ->
            api.monthlyStats(query.month, query.tag.ifBlank { null }, query.timezone, query.homeCurrencyCode)
        }

    override suspend fun lifestyleStats(query: StatsQuery): Result<StatsRead<LifestyleStats>> =
        read(query.copy(tag = ""), StatsProjectionKind.Lifestyle, lifestyleAdapter,
            { dto -> dto.month to dto.homeCurrencyCode }, LifestyleStatsDto::toDomain) { api ->
            api.lifestyleStats(query.month, query.timezone, query.homeCurrencyCode)
        }

    private suspend fun <W, D> read(
        query: StatsQuery,
        kind: StatsProjectionKind,
        adapter: JsonAdapter<W>,
        scope: (W) -> Pair<String, String>,
        project: (W) -> D,
        fetch: suspend (com.ticketbox.data.remote.ApiService) -> W,
    ): Result<StatsRead<D>> {
        val token = Any()
        cacheMutex.withLock { latestReads[kind] = token }
        val result = core.errorHandler.safeCall {
            YearMonth.parse(query.month)
            ZoneId.of(query.timezone)
            val bound = core.ledgerRequestGuard.bindExact(query.binding)
            val wire = bound.call { fetch(it) }
            validateScope(query, scope(wire))
            val value = project(wire)
            val row = StatsProjectionCacheEntity(
                bindingKey = bindingAdapter.toJson(query.binding), ledgerId = query.binding.ledgerId,
                kind = kind.storageKey, month = query.month, tag = query.tag.trim(), homeCurrencyCode = scope(wire).second,
                timezone = query.timezone, responseJson = adapter.toJson(wire), fetchedAt = Instant.now().toString(),
            )
            core.withActiveBindingCommit(bound) {
                cacheMutex.withLock {
                    if (latestReads[kind] === token) core.expenseDao.saveStatsProjection(row)
                }
            }
            StatsRead(value, row.fetchedAt, fromCache = false)
        }
        if (result.isSuccess || statsBinding() != query.binding) return result
        val cached = core.expenseDao.statsProjection(
            bindingAdapter.toJson(query.binding), kind.storageKey, query.month, query.tag.trim(), query.homeCurrencyCode, query.timezone,
        ) ?: return result
        val restored = runCatching {
            val wire = requireNotNull(adapter.fromJson(cached.responseJson))
            validateScope(query.copy(homeCurrencyCode = cached.homeCurrencyCode), scope(wire))
            check(statsBinding() == query.binding)
            StatsRead(project(wire), cached.fetchedAt, fromCache = true)
        }
        return if (restored.isSuccess) restored else result
    }

    private fun validateScope(query: StatsQuery, scope: Pair<String, String>) {
        if (scope.first != query.month || scope.second.isBlank() ||
            (query.homeCurrencyCode != null && query.homeCurrencyCode != scope.second)) {
            throw RepositoryException("stats_projection_unverified", localFailure = LocalRepositoryFailure.StatsProjectionUnverified)
        }
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = ledgerActions.syncConfirmed(
        month = month,
        category = category,
        tag = tag,
    )

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.dataQualitySummary().toDomain()
        }
    }
}
