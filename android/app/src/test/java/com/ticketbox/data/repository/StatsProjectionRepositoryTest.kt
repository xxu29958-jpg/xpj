package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import java.net.ConnectException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class StatsProjectionRepositoryTest {
    @Test
    fun earlierMonthReadReturningLastCannotReplaceTheNewerSnapshot() = runTest {
        assertLatestMonthReadOwnsCache(earlierReturnsFirst = false)
    }

    @Test
    fun supersededMonthReadReturningFirstCannotInstallAnIntermediateSnapshot() = runTest {
        assertLatestMonthReadOwnsCache(earlierReturnsFirst = true)
    }

    @Test
    fun anotherResponseCurrencyCannotReplaceTheOriginalQuerySnapshot() = runTest {
        val api = ProjectionApi()
        val repository = projectionRepository(FakeExpenseDao(), api)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", homeCurrencyCode = "JPY")
        val original = repository.monthlyStats(query).getOrThrow()
        api.response = api.response.copy(homeCurrencyCode = "CNY", totalAmountCents = 9000)
        assertTrue(repository.monthlyStats(query).isFailure)
        api.offline = true
        val preserved = repository.monthlyStats(query).getOrThrow()
        assertEquals(original.value, preserved.value)
        assertEquals(original.fetchedAt, preserved.fetchedAt)
    }

    @Test
    fun malformedLaterLifestyleResponseCannotOverwriteTheReadableSnapshot() = runTest {
        val api = ProjectionApi()
        val repository = projectionRepository(FakeExpenseDao(), api)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", homeCurrencyCode = "CNY")
        val original = repository.lifestyleStats(query).getOrThrow()
        api.lifestyleExpense = api.lifestyleExpense.copy(publicId = null, amountCents = 9000)
        assertTrue(repository.lifestyleStats(query).isFailure)
        api.offline = true
        val offline = repository.lifestyleStats(query).getOrThrow()
        assertEquals(original.value, offline.value)
        assertEquals(original.fetchedAt, offline.fetchedAt)
    }

    @Test
    fun lifestyleCacheKeepsRecordCurrencyDistinctFromProjectedTotals() = runTest {
        val api = ProjectionApi()
        val repository = projectionRepository(FakeExpenseDao(), api)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", homeCurrencyCode = "CNY")
        repository.lifestyleStats(query).getOrThrow()
        api.offline = true
        val saved = repository.lifestyleStats(query).getOrThrow()
        assertTrue(saved.fromCache)
        assertEquals("CNY", saved.value.homeCurrencyCode)
        assertEquals(500L, saved.value.digitalAmountCents)
        val original = requireNotNull(saved.value.maxExpense)
        assertEquals("JPY", original.homeCurrencyCode)
        assertEquals(1000L, original.amountCents)
        assertEquals(com.ticketbox.domain.model.CurrencyCode.JPY,
            com.ticketbox.ui.screens.stats.lifestyleRecordCurrency(original).homeCurrency)
    }

    @Test
    fun offlineReadRestoresTheServerNetSnapshotWithoutSummingRootFacts() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(9, "root-9", "MUJI").copy(amountCents = 10000, homeCurrencyCode = "CNY"))
        val api = ProjectionApi()
        val session = TestSessionFixture().apply { saveToken("session-token") }
        val repository = projectionRepository(dao, api, session)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", "旅行", timezone = "Asia/Tokyo")
        val first = repository.monthlyStats(query).getOrThrow()
        assertFalse(first.fromCache)
        assertEquals(7000L, first.value.totalAmountCents)
        api.offline = true
        val reopened = projectionRepository(dao, api, session)
        val saved = reopened.monthlyStats(query.copy(homeCurrencyCode = "JPY")).getOrThrow()
        assertTrue(saved.fromCache)
        assertEquals(first.fetchedAt, saved.fetchedAt)
        assertEquals(first.value, saved.value)
        assertEquals("JPY", saved.value.homeCurrencyCode)
        assertEquals(listOf<String?>("旅行", "旅行"), api.tags)
    }

    @Test
    fun cacheCannotCrossTagMonthHomeTimezoneOrBindingAndClearRetiresIt() = runTest {
        val dao = FakeExpenseDao()
        val api = ProjectionApi()
        val repository = projectionRepository(dao, api)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", "旅行", timezone = "Asia/Tokyo")
        repository.monthlyStats(query).getOrThrow()
        api.offline = true
        val otherQueries = listOf(query.copy(tag = ""), query.copy(month = "2026-08"),
            query.copy(homeCurrencyCode = "CNY"), query.copy(timezone = "UTC"),
            query.copy(binding = query.binding.copy(bindingRevision = "other")))
        otherQueries.forEach { assertTrue(repository.monthlyStats(it).isFailure) }
        dao.clearAllExpenseCachesForLedger(query.binding.ledgerId)
        assertTrue(repository.monthlyStats(query).isFailure)
    }

    @Test
    fun cachedUnknownAmountsAndGapDoNotTurnIntoZeroOrLoseCounts() = runTest {
        val api = ProjectionApi().apply { response = response.copy(totalAmountCents = null,
            byCategory = listOf(CategoryStatsDto("购物", null, 2)),
            missingRates = listOf(MissingExchangeRateDto("CNY", "JPY", "2026-09-03"))) }
        val repository = projectionRepository(FakeExpenseDao(), api)
        val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09")
        val read = repository.monthlyStats(query).getOrThrow()
        api.offline = true
        val saved = repository.monthlyStats(query).getOrThrow()
        assertEquals(read.value, saved.value)
        assertEquals(null, saved.value.totalAmountCents)
        assertEquals(null, saved.value.byCategory.single().amountCents)
        assertEquals(2, saved.value.count)
        assertEquals("2026-09-03", saved.value.missingRates.single().rateDate)
    }
}

private suspend fun CoroutineScope.assertLatestMonthReadOwnsCache(earlierReturnsFirst: Boolean) {
    val dao = FakeExpenseDao()
    val api = ProjectionApi()
    val repository = projectionRepository(dao, api)
    val query = StatsQuery(requireNotNull(repository.statsBinding()), "2026-09", homeCurrencyCode = "JPY")
    repository.monthlyStats(query).getOrThrow()
    val earlierResponse = CompletableDeferred<MonthlyStatsDto>()
    val latestResponse = CompletableDeferred<MonthlyStatsDto>()
    val earlierStarted = CompletableDeferred<Unit>()
    val latestStarted = CompletableDeferred<Unit>()
    var septemberReads = 0
    api.monthlyResponder = { month ->
        when {
            month != query.month -> api.response.copy(month = requireNotNull(month))
            septemberReads++ == 0 -> { earlierStarted.complete(Unit); earlierResponse.await() }
            else -> { latestStarted.complete(Unit); latestResponse.await() }
        }
    }
    val earlier = async { repository.monthlyStats(query).getOrThrow() }
    earlierStarted.await()
    repository.monthlyStats(query.copy(month = "2026-08")).getOrThrow()
    val latest = async { repository.monthlyStats(query).getOrThrow() }
    latestStarted.await()
    if (earlierReturnsFirst) {
        earlierResponse.complete(api.response.copy(totalAmountCents = 8000))
        earlier.await()
        assertCachedTotal(dao, query, 7000)
    }
    latestResponse.complete(api.response.copy(totalAmountCents = 9000))
    assertEquals(9000L, latest.await().value.totalAmountCents)
    if (!earlierReturnsFirst) {
        earlierResponse.complete(api.response.copy(totalAmountCents = 8000))
        earlier.await()
    }
    api.offline = true
    val restored = repository.monthlyStats(query).getOrThrow()
    assertTrue(restored.fromCache)
    assertEquals(9000L, restored.value.totalAmountCents)
}

private suspend fun assertCachedTotal(dao: FakeExpenseDao, query: StatsQuery, expected: Long) {
    val moshi = Moshi.Builder().build()
    val key = moshi.adapter(LogicalSessionBinding::class.java).toJson(query.binding)
    val row = dao.statsProjections(key, "monthly", query.month, query.tag, query.timezone)
        .single { it.homeCurrencyCode == query.homeCurrencyCode }
    assertEquals(expected, moshi.adapter(MonthlyStatsDto::class.java).fromJson(row.responseJson)?.totalAmountCents)
}

private class ProjectionApi : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
    var offline = false
    var monthlyResponder: (suspend (String?) -> MonthlyStatsDto)? = null
    val tags = mutableListOf<String?>()
    var response = MonthlyStatsDto(homeCurrencyCode = "JPY", month = "2026-09", totalAmountCents = 7000,
        count = 2, byCategory = listOf(CategoryStatsDto("购物", 7000, 2)))
    var lifestyleExpense = confirmedExpenseDtoFixture().copy(homeCurrency = "JPY", originalCurrencyCode = "JPY", amountCents = 1000)
    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?): MonthlyStatsDto {
        tags.add(tag)
        if (offline) throw ConnectException("offline")
        return monthlyResponder?.invoke(month) ?: response
    }
    override suspend fun lifestyleStats(month: String?, timezone: String?, homeCurrencyCode: String?): LifestyleStatsDto {
        if (offline) throw ConnectException("offline")
        return LifestyleStatsDto(homeCurrencyCode = "CNY", month = "2026-09", aiSubscriptionAmountCents = 0,
            digitalAmountCents = 500, recent7DaysAmountCents = 500, frequentMerchants = emptyList(),
            maxExpense = lifestyleExpense)
    }
}

private fun projectionRepository(dao: FakeExpenseDao, api: ApiService, session: TestSessionFixture = TestSessionFixture().apply { saveToken("session-token") }): ExpenseRepository = expenseRepositoryFixture(
    expenseDao = dao,
    binding = testServerSessionBinding(
        apiClient = object : com.ticketbox.data.remote.ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
        }, settingsStore = boundSettingsStore(),
        tokenStore = session,
    ),
)
