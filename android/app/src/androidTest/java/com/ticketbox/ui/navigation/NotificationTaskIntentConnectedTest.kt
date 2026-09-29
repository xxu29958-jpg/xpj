package com.ticketbox.ui.navigation

import android.Manifest
import android.app.NotificationManager
import android.app.Notification
import android.content.Context
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.NotificationRuntimeGraph
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.budget.BudgetOverspendDispatchOutcome
import com.ticketbox.notification.budget.BudgetOverspendDecision
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotificationTaskIntentConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val fixture = ExpenseCorrectionConnectedFixture(context)

    @After fun close() = fixture.close()

    @Test fun differentBudgetTasksKeepSeparateSystemOpenActions() = runBlocking {
        fixture.reopen()
        val runtime = NotificationRuntimeGraph(fixture.notificationDependencies.copy(settingsStore =
            object : TicketboxSettingsStore by fixture.settingsStore {
                override fun notificationPreferences() = NotificationPreferences(budgetOverspendAlerts = true)
            }))
        val binding = requireNotNull(fixture.notificationDependencies.ledgerCalendarRepository.currentBinding())
        val manager = context.getSystemService(NotificationManager::class.java)
        val first = "notification-original-budget-september"
        val second = "notification-original-budget-october"
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                InstrumentationRegistry.getInstrumentation().uiAutomation.grantRuntimePermission(
                    context.packageName, Manifest.permission.POST_NOTIFICATIONS)
            }
            assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent(BudgetOverspendDecision(first, binding.ledgerId, "2026-09", 30000, "CNY"), binding))
            assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent(BudgetOverspendDecision(second, binding.ledgerId, "2026-10", 1200, "JPY"), binding))
            val posted = withTimeout(5_000) {
                var notifications = manager.activeNotifications.filter { it.tag == first || it.tag == second }
                while (notifications.size != 2) {
                    delay(50)
                    notifications = manager.activeNotifications.filter { it.tag == first || it.tag == second }
                }
                notifications.associateBy { it.tag }
            }
            assertNotEquals("Two original budget tasks must not share one system PendingIntent",
                requireNotNull(posted[first]).notification.contentIntent,
                requireNotNull(posted[second]).notification.contentIntent)
            assertEquals(context.getString(com.ticketbox.R.string.notification_budget_overspent_body, "¥1,200"),
                requireNotNull(posted[second]).notification.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString())
        } finally {
            manager.cancel(first, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            manager.cancel(second, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
        }
    }
}
