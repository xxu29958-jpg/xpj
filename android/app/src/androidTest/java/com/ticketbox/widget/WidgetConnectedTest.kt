package com.ticketbox.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.widget.FrameLayout
import android.widget.TextView
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.readWidgetMonthlySummary
import com.ticketbox.domain.model.LedgerCalendar
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.StoredSessionToken
import com.ticketbox.ui.navigation.EXTRA_SHORTCUT_TARGET
import com.ticketbox.ui.navigation.ShortcutTarget
import java.net.ConnectException
import java.time.YearMonth
import java.time.ZoneOffset
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WidgetConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun manifestPublishesBothWidgetsAndEveryActionHasItsOwnPendingIntent() {
        val manager = AppWidgetManager.getInstance(context)
        val names = manager.installedProviders.map { it.provider }
        assertTrue(ComponentName(context, QuickEntryWidgetProvider::class.java) in names)
        assertTrue(ComponentName(context, MonthlyOverviewWidgetProvider::class.java) in names)
        val intents = ShortcutTarget.entries.map { target ->
            val intent = widgetLaunchIntent(context, target)
            assertEquals(context.packageName, intent.component?.packageName)
            assertEquals(target.id, intent.getStringExtra(EXTRA_SHORTCUT_TARGET))
            PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
        assertEquals(4, intents.toSet().size)
    }

    @Test fun privacyConsentIsPerWidgetAndDoesNotFollowRebindingOrRestoration() {
        val preferences = WidgetPreferences(context)
        val version = widgetTestSession().version
        try {
            assertFalse(preferences.allowsSummary(TEST_ID, version))
            preferences.save(TEST_ID, version)
            assertTrue(WidgetPreferences(context).allowsSummary(TEST_ID, version))
            assertFalse(preferences.allowsSummary(TEST_ID + 1, version))
            assertFalse(preferences.allowsSummary(TEST_ID, version.copy(bindingRevision = "other-ledger")))
            assertFalse(preferences.allowsSummary(TEST_ID, version.copy(sessionGeneration = "other-account")))
            assertFalse(preferences.allowsSummary(TEST_ID, null))
            MonthlyOverviewWidgetProvider().onRestored(context, intArrayOf(TEST_ID), intArrayOf(TEST_ID + 1))
            assertFalse(preferences.allowsSummary(TEST_ID, version))
        } finally { preferences.remove(intArrayOf(TEST_ID, TEST_ID + 1)) }
    }

    @Test fun remoteViewsHideFinancialContentUntilConsentedAndUseOriginalCurrency() {
        val snapshot = ReadSnapshot(MonthlyStats("JPY", month = "2026-11", totalAmountCents = 7000,
            count = 2, byCategory = emptyList()), "2026-11-01T01:00:00Z", fromCache = true)
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            val hidden = inflate(WidgetOverviewState(widgetTestSession(), snapshot))
            assertEquals(context.getString(R.string.widget_amount_hidden), hidden.text(R.id.widget_amount))
            assertEquals(context.getString(R.string.widget_brand), hidden.text(R.id.widget_ledger))
            val shown = inflate(WidgetOverviewState(widgetTestSession(), snapshot, showSummary = true))
            assertEquals("¥7,000", shown.text(R.id.widget_amount))
            assertTrue(shown.text(R.id.widget_updated).startsWith("离线快照"))
            assertTrue(shown.text(R.id.widget_title).contains("2026-11"))
            val missing = inflate(WidgetOverviewState(widgetTestSession(), snapshot.copy(
                value = snapshot.value.copy(totalAmountCents = null)), showSummary = true))
            assertEquals(context.getString(R.string.widget_missing_rates), missing.text(R.id.widget_amount))
            val unbound = inflate(WidgetOverviewState(null, snapshot, showSummary = true))
            assertEquals(context.getString(R.string.widget_bind_first), unbound.text(R.id.widget_amount))
        }
    }

    @Test fun summaryReadsServerProjectionAndRecoversItsOriginalSnapshotOffline() = runBlocking {
        var offline = false
        val fixture = ExpenseCorrectionConnectedFixture(context) { delegate ->
            object : ApiService by delegate {
                override suspend fun runtimeCompatibility() = delegate.runtimeCompatibility().let {
                    it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1))
                }
                override suspend fun ledgerCalendar(ledgerId: String, revision: Long?) =
                    LedgerCalendar(ledgerId, 1, "UTC", "explicit", "2026-01-01T00:00:00Z")
                override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?): MonthlyStatsDto {
                    if (offline) throw ConnectException("offline widget fixture")
                    assertNull(tag)
                    return MonthlyStatsDto("JPY", month = requireNotNull(month), totalAmountCents = 7000,
                        count = 2, byCategory = emptyList())
                }
            }
        }
        try {
            val repository = fixture.reopen().expenseRepository
            val first = readWidgetMonthlySummary(repository, fixture.ledgerCalendarRepository).getOrThrow()
            assertEquals(YearMonth.now(ZoneOffset.UTC).toString(), first.value.month)
            assertEquals(7000L, first.value.totalAmountCents)
            offline = true
            val restoredRepository = fixture.reopen().expenseRepository
            val cached = readWidgetMonthlySummary(restoredRepository, fixture.ledgerCalendarRepository).getOrThrow()
            assertTrue(cached.fromCache)
            assertEquals(first.value, cached.value)
            assertEquals(first.fetchedAt, cached.fetchedAt)
            fixture.switchLedger()
            assertTrue(readWidgetMonthlySummary(restoredRepository, fixture.ledgerCalendarRepository).isFailure)
        } finally { fixture.close() }
    }

    private fun inflate(state: WidgetOverviewState): android.view.View =
        monthlyOverviewViews(context, TEST_ID, state).apply(context, FrameLayout(context))

    private fun android.view.View.text(id: Int) = findViewById<TextView>(id).text.toString()

    companion object { private const val TEST_ID = 987654 }
}

private fun widgetTestSession() = LocalSessionRecord(
    sessionGeneration = "widget-test-session", bindingRevision = "widget-test-binding",
    serverId = "60000000-0000-4000-8000-000000000001", dataGeneration = "60000000-0000-4000-8000-000000000002",
    serverUrl = "https://widget.example.test", credential = StoredSessionToken("synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "60000000-0000-4000-8000-000000000003",
        devicePublicId = "60000000-0000-4000-8000-000000000004", accountName = "测试成员", ledgerId = "widget-ledger",
        ledgerName = "测试账本", deviceName = "测试手机", role = "member", boundAt = "2026-11-01T00:00:00Z"),
)
