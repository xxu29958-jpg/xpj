package com.ticketbox.ui.navigation

import android.app.NotificationManager
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.TicketboxApplication
import com.ticketbox.data.repository.newTaskMonth
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.backup.BackupStaleRunOutcome
import com.ticketbox.notification.boundReminderKey
import com.ticketbox.notification.budget.SharedPrefsBudgetOverspendStore
import com.ticketbox.notification.budget.budgetOverspendSentKey
import com.ticketbox.notification.recurring.RecurringReminderRunOutcome
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Invoke the installed app's scheduled checks; all sources use the journey's real HTTP/PG. */
class NotificationJourneyRuntimeTest {
    @Test fun freshSourcesRespectRealChannelsAndRetainTheirOriginalDelivery() = runBlocking {
        val arguments = InstrumentationRegistry.getArguments()
        check(arguments.getString("ticketboxNotificationJourney") == "isolated-cloud")
        check(Build.PRODUCT.contains("sdk"))
        val context = ApplicationProvider.getApplicationContext<TicketboxApplication>()
        val container = context.container
        val binding = withTimeout(20_000) {
            var current = container.expenseRepository.captureDeferredLedgerBinding()
            while (current == null) { delay(100); current = container.expenseRepository.captureDeferredLedgerBinding() }
            current
        }
        val uri = java.net.URI(binding.serverUrl)
        check(uri.host == "127.0.0.1" && uri.port == 18880)
        val stage = arguments.getString("channels")
        check(stage in setOf("blocked", "enabled"))
        val enabled = stage == "enabled"
        val preferences = container.settingsStore.notificationPreferences()
        assertTrue(preferences.recurringReminders && preferences.budgetOverspendAlerts && preferences.backupStaleAlerts)
        val manager = context.getSystemService(NotificationManager::class.java)
        val channels = setOf(TicketboxNotifier.CHANNEL_RECURRING, TicketboxNotifier.CHANNEL_BUDGET, TicketboxNotifier.CHANNEL_BACKUP)
        channels.forEach { channel ->
            assertEquals("The actual OS channel must match the user's setting", enabled,
                requireNotNull(manager.getNotificationChannel(channel)).importance != NotificationManager.IMPORTANCE_NONE)
        }
        val recurring = container.recurringReminderEngine.checkAndNotify() as RecurringReminderRunOutcome.Success
        val backup = container.backupStaleEngine.checkAndNotify() as BackupStaleRunOutcome.Success
        container.budgetOverspendChecker.checkNow(binding.ledgerId)
        assertEquals(1, recurring.due)
        if (!enabled) {
            assertEquals(1, recurring.skippedDispatch)
            assertEquals(BackupStaleRunOutcome.Detail.SKIPPED_DISPATCH, backup.detail)
        }
        val key = boundReminderKey(binding, budgetOverspendSentKey(binding.ledgerId, container.ledgerCalendarRepository.newTaskMonth()))
        assertEquals("A refused notification is not an already-delivered reminder", enabled,
            SharedPrefsBudgetOverspendStore(context).wasSent(key))

        fun deliveries() = manager.activeNotifications.filter { it.notification.channelId in channels }.associate { it.tag to it.postTime }
        withTimeout(10_000) { while (deliveries().size != if (enabled) 3 else 0) delay(100) }
        val originals = deliveries()
        container.recurringReminderEngine.checkAndNotify()
        container.backupStaleEngine.checkAndNotify()
        container.budgetOverspendChecker.checkNow(binding.ledgerId)
        assertEquals("Another check must not replace an already-delivered original", originals, deliveries())
    }
}
