package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.StatsProjectionCacheEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryStatsDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.StatsQuery
import com.ticketbox.data.repository.toDomain
import com.ticketbox.data.repository.toEntity
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.StatsSource
import java.net.ConnectException
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual StatsRoute + disk Room; transport alone supplies the server projection. */
class MonthlyStatsSnapshotConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val base = DataQualityConnectedHarness()
    private val mounted = mutableStateOf(false)
    private val models = object : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }
    private val shell = MainShellState()
    @Volatile private var offline = false
    private var missingRate = false
    private var recovery: ReportRateContext? = null
    private val fixture = ExpenseCorrectionConnectedFixture(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?): MonthlyStatsDto {
                if (offline) throw ConnectException("offline stats")
                return MonthlyStatsDto(homeCurrencyCode = "JPY", month = requireNotNull(month),
                    totalAmountCents = if (missingRate) null else 7000, count = 2,
                    byCategory = listOf(CategoryStatsDto("购物", if (missingRate) null else 7000, 2)),
                    missingRates = if (missingRate) listOf(MissingExchangeRateDto("CNY", "JPY", "2026-08-05")) else emptyList())
            }
            override suspend fun lifestyleStats(month: String?, timezone: String?, homeCurrencyCode: String?): LifestyleStatsDto {
                throw ConnectException("lifestyle offline")
            }
        }
    }
    private lateinit var monthly: MonthlyStatsViewModel

    @After fun close() {
        compose.runOnIdle { mounted.value = false; models.viewModelStore.clear() }
        compose.waitForIdle()
        fixture.close()
        base.close()
    }

    @Test fun offlineRouteRestoresOriginalServerNetAndClearKeepsOriginalOutboxBytes() {
        val before = prepare()
        show()
        awaitSnapshot()
        assertEquals(7000L, monthly.uiState.value.stats?.totalAmountCents)
        assertEquals("2026-09", monthly.uiState.value.stats?.month)
        assertEquals("JPY", monthly.uiState.value.stats?.homeCurrencyCode)
        assertNotNull(monthly.uiState.value.statsFetchedAt)
        compose.onNodeWithText(context.getString(R.string.stats_projection_currency, "JPY")).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("stats-cached-snapshot").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("stats-monthly-total").performScrollTo()
            .assertTextEquals(com.ticketbox.ui.components.formatDisplayAmount(7000, CurrencyDisplay(CurrencyCode.JPY)))
        runBlocking { fixture.expenseDao.clearAllExpenseCaches() }
        assertEquals(before, fixture.stored())
        val repo = fixture.graph.expenseRepository
        assertTrue(runBlocking { repo.monthlyStats(StatsQuery(requireNotNull(repo.statsBinding()), "2026-09")).isFailure })
    }

    @Test fun unknownProjectionOpensItsOriginalRateContextAndBindingReplacementHidesTheSnapshot() {
        missingRate = true
        val before = prepare()
        show()
        awaitSnapshot()
        assertNull(monthly.uiState.value.stats?.totalAmountCents)
        assertEquals(2, monthly.uiState.value.stats?.count)
        compose.onNodeWithTag("stats-monthly-total").performScrollTo()
            .assertTextEquals(context.getString(R.string.reports_amount_unavailable))
        compose.onNodeWithTag("stats-rate-CNY-2026-08-05").performScrollTo().assertIsDisplayed().performClick()
        assertEquals(ReportRateContext(requireNotNull(monthly.uiState.value.binding), "2026-09", "JPY", "CNY", "2026-08-05"), recovery)
        compose.runOnIdle { fixture.switchLedger() }
        compose.waitUntil(5_000) { monthly.uiState.value.activeLedgerId == "another-ledger" && !monthly.uiState.value.loading }
        assertNull(monthly.uiState.value.stats)
        assertNull(monthly.uiState.value.lifestyleStats)
        compose.onNodeWithTag("stats-cached-snapshot").assertDoesNotExist()
        assertEquals(before, fixture.stored())
    }

    @Test fun diskSnapshotsKeepBothHomesAndOnlyAnUnspecifiedHomeSelectsTheLatest() {
        val repo = fixture.reopen().expenseRepository
        val binding = requireNotNull(repo.statsBinding())
        val query = StatsQuery(binding, "2026-09", "旅行", timezone = "Asia/Tokyo")
        val moshi = Moshi.Builder().build()
        val bindingKey = moshi.adapter(LogicalSessionBinding::class.java).toJson(binding)
        val adapter = moshi.adapter(MonthlyStatsDto::class.java)
        runBlocking {
            listOf("JPY" to 7000L, "USD" to 1200L).forEachIndexed { index, (home, amount) ->
                val wire = MonthlyStatsDto(home, month = query.month, totalAmountCents = amount,
                    count = 2, byCategory = listOf(CategoryStatsDto("购物", amount, 2)))
                fixture.expenseDao.saveStatsProjection(StatsProjectionCacheEntity(
                    bindingKey, binding.ledgerId, "monthly", query.month, query.tag, home,
                    query.timezone, adapter.toJson(wire), "2026-09-09T00:00:0${index}Z",
                ))
            }
        }
        offline = true
        val reopened = fixture.reopen().expenseRepository
        runBlocking {
            val original = reopened.monthlyStats(query.copy(homeCurrencyCode = "JPY")).getOrThrow()
            assertTrue(original.fromCache)
            assertEquals("JPY", original.value.homeCurrencyCode)
            assertEquals(7000L, original.value.totalAmountCents)
            val latest = reopened.monthlyStats(query).getOrThrow()
            assertEquals("USD", latest.value.homeCurrencyCode)
            assertEquals(1200L, latest.value.totalAmountCents)
            assertTrue(reopened.monthlyStats(query.copy(homeCurrencyCode = "CNY")).isFailure)
        }
    }

    private fun prepare(): List<Map<String, String?>> {
        val graph = fixture.reopen()
        val repo = graph.expenseRepository
        val binding = requireNotNull(repo.statsBinding())
        runBlocking {
            fixture.expenseDao.insert(fixture.network.current.copy(amountCents = 10000).toEntity(binding.ledgerId))
            repo.monthlyStats(StatsQuery(binding, "2026-09")).getOrThrow()
            repo.submitCorrection(binding, fixture.network.current.toDomain(),
                ExpenseCorrectionDraft("统计缓存验证保留原提交", note = "原稿在清理统计缓存后仍保留")).getOrThrow()
        }
        val before = fixture.stored()
        offline = true
        fixture.reopen()
        return before
    }

    private fun show() {
        val graph = fixture.graph
        val factory = MainScreenFactory(base.screenFactory.repositories.copy(
            repository = graph.expenseRepository, ledgerRepository = graph.ledgerRepository,
            budgetRepository = graph.budgetRepository, recurringRepository = graph.recurringRepository,
            reportsRepository = graph.reportsRepository, outboxRepository = fixture.outbox,
        ), base.screenFactory.viewModelFactories)
        compose.runOnIdle {
            monthly = ViewModelProvider(models, viewModelFactory {
                initializer { MonthlyStatsViewModel(graph.expenseRepository, initialMonth = "2026-09") }
            })[MonthlyStatsViewModel::class.java]
            mounted.value = true
        }
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides models,
                    LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                    if (mounted.value) StatsRoute(shell, factory, onRepairReport = { recovery = it })
                }
            }
        }
    }

    private fun awaitSnapshot() {
        compose.waitUntil(5_000) { monthly.uiState.value.statsSource == StatsSource.CachedSnapshot }
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("stats-cached-snapshot")).fetchSemanticsNodes().isNotEmpty() }
    }
}
