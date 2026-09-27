package com.ticketbox.ui.navigation

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.NotificationRuntimeGraph
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.newTaskMonth
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.budget.BudgetOverspendDispatchOutcome
import com.ticketbox.notification.budget.SharedPrefsBudgetOverspendStore
import com.ticketbox.notification.budget.budgetOverspendSentKey
import java.util.TimeZone
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real repository graph and disk Room; control only the budget HTTP response. */
@RunWith(AndroidJUnit4::class)
class BudgetOfflineSnapshotConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = OfflineBudgetTransport()
    private val fixture = ExpenseCorrectionConnectedFixture(context, transport::wrap)

    @After fun close() = fixture.close()

    @Test fun septemberUnknownValuesSurviveReopenButAnotherMonthTimezoneAndRefusalCannotBorrowThem() = runBlocking {
        transport.original = offlineBudget().copy(fixedAmountCents = null, flexBudgetCents = null,
            spentAmountCents = null, remainingAmountCents = null, overspentAmountCents = null,
            missingCurrencyCodes = listOf("USD"))
        fixture.reopen().budgetRepository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").getOrThrow()
        val originalIntents = fixture.stored()
        transport.offline = true
        val repository = fixture.reopen().budgetRepository

        val saved = repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai")
        assertTrue("Previously read September must survive reopening disk Room offline", saved.isSuccess)
        assertEquals(transport.original.toDomain(), saved.getOrThrow())
        assertTrue(repository.monthlyBudget("2026-10", timezone = "Asia/Shanghai").isFailure)
        assertTrue(repository.monthlyBudget("2026-09", timezone = "America/Los_Angeles").isFailure)

        transport.denied = true
        assertTrue(repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        transport.denied = false
        assertTrue("The refused snapshot must not return when the transport fails again",
            repository.monthlyBudget("2026-09", timezone = "Asia/Shanghai").isFailure)
        assertEquals(originalIntents, fixture.stored())
    }

    @Test fun replacingTheBindingCannotExposeTheOriginalMonthlyBudget() = runBlocking {
        fixture.reopen().budgetRepository.monthlyBudget("2026-09").getOrThrow()
        transport.offline = true
        val repository = fixture.reopen().budgetRepository
        assertTrue("First establish the saved read under its original binding", repository.monthlyBudget("2026-09").isSuccess)

        fixture.switchLedger()

        assertTrue(repository.monthlyBudget("2026-09").isFailure)
    }

    @Test fun anOfflineOverspendSnapshotCannotConsumeANewNotificationSentKey() = runBlocking {
        val graph = fixture.reopen()
        val calendars = graph.ledgerCalendarRepository
        calendars.refresh(requireNotNull(calendars.currentBinding())).getOrThrow()
        val month = calendars.newTaskMonth()
        val queryTimezone = TimeZone.getDefault().id
        transport.original = offlineBudget().copy(spentAmountCents = 1500, remainingAmountCents = -300, overspentAmountCents = 300)
        graph.budgetRepository.monthlyBudget(month, timezone = queryTimezone).getOrThrow()
        transport.offline = true
        fixture.reopen()
        val runtime = NotificationRuntimeGraph(fixture.notificationDependencies.copy(settingsStore =
            object : TicketboxSettingsStore by fixture.settingsStore {
                override fun notificationPreferences() = NotificationPreferences(budgetOverspendAlerts = true)
            }))
        val key = budgetOverspendSentKey("correction-ledger", month)
        val preferences = context.getSharedPreferences(SharedPrefsBudgetOverspendStore.PREFS_NAME, Context.MODE_PRIVATE)
        val originalValue = if (preferences.contains(key)) preferences.getBoolean(key, false) else null
        preferences.edit().remove(key).commit()
        val manager = context.getSystemService(NotificationManager::class.java)
        val probeTag = "budget-offline-reading-delivery-probe"
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                InstrumentationRegistry.getInstrumentation().uiAutomation.grantRuntimePermission(
                    context.packageName, Manifest.permission.POST_NOTIFICATIONS)
            }
            // Prove a decision would reach SENT; disabled OS delivery must not make this test falsely green.
            assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent("¥300", probeTag))
            val previousReads = transport.reads.size
            runtime.budgetOverspendChecker.checkNow("correction-ledger")
            assertEquals("The real graph must attempt its live budget query", previousReads + 1, transport.reads.size)
            assertEquals("Cache warmup and the real notification must address the same query",
                month to queryTimezone, transport.readScopes.last())
            assertTrue("The real graph must not mark a cached overspend as newly notified", !preferences.contains(key))
            assertTrue(manager.activeNotifications.none { it.tag == key })
        } finally {
            manager.cancel(probeTag, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            manager.cancel(key, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            if (originalValue == null) preferences.edit().remove(key).commit()
            else preferences.edit().putBoolean(key, originalValue).commit()
        }
    }
}
