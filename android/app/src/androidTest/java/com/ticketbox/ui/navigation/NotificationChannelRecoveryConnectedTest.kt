package com.ticketbox.ui.navigation

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.view.KeyEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.NotificationRuntimeGraph
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.budget.BudgetOverspendDecision
import com.ticketbox.notification.budget.BudgetOverspendDispatchOutcome
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** A real OS channel refusal must remain retryable; the application does not override the user's channel. */
class NotificationChannelRecoveryConnectedTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val fixture = ExpenseCorrectionConnectedFixture(context)
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val manager = context.getSystemService(NotificationManager::class.java)
    private val tag = "original-budget-channel-recovery"

    @After fun close() = fixture.close()

    @Test fun aDisabledChannelIsNotReportedAsSentAndEnablingItAllowsTheOriginalTask() = runBlocking {
        fixture.reopen()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        val runtime = NotificationRuntimeGraph(fixture.notificationDependencies.copy(settingsStore =
            object : TicketboxSettingsStore by fixture.settingsStore {
                override fun notificationPreferences() = NotificationPreferences(budgetOverspendAlerts = true)
            }))
        val binding = requireNotNull(fixture.notificationDependencies.ledgerCalendarRepository.currentBinding())
        val original = BudgetOverspendDecision(tag, binding.ledgerId, "2026-09", 1200, "JPY")
        assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent(original, binding))
        manager.cancel(tag, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
        context.startActivity(Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
            .putExtra(Settings.EXTRA_CHANNEL_ID, TicketboxNotifier.CHANNEL_BUDGET)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        try {
            setChannelEnabled(false)
            assertEquals(BudgetOverspendDispatchOutcome.SKIPPED_PERMISSION_DENIED,
                runtime.notifier.onBudgetOverspent(original, binding))
            assertTrue(manager.activeNotifications.none { it.tag == tag })
            setChannelEnabled(true)
            assertEquals(BudgetOverspendDispatchOutcome.SENT, runtime.notifier.onBudgetOverspent(original, binding))
            withTimeout(5_000) { while (manager.activeNotifications.none { it.tag == tag }) delay(50) }
        } finally {
            if (manager.getNotificationChannel(TicketboxNotifier.CHANNEL_BUDGET)?.importance == NotificationManager.IMPORTANCE_NONE) {
                setChannelEnabled(true)
            }
            manager.cancel(tag, TicketboxNotifier.DRAFT_NOTIFICATION_ID)
            instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        }
    }

    private suspend fun setChannelEnabled(enabled: Boolean) {
        val toggle = withTimeout(8_000) {
            var found: AccessibilityNodeInfo? = null
            while (found == null) {
                val root = instrumentation.uiAutomation.rootInActiveWindow
                if (root?.packageName?.toString() == "com.android.settings") found = findChannelSwitch(root)
                if (found == null) delay(100)
            }
            found
        }
        if (toggle.isChecked != enabled) {
            val action = generateSequence(toggle) { it.parent }.first { it.isClickable }
            assertTrue("The actual system channel control must accept the change", action.performAction(AccessibilityNodeInfo.ACTION_CLICK))
        }
        withTimeout(5_000) {
            while ((manager.getNotificationChannel(TicketboxNotifier.CHANNEL_BUDGET)?.importance !=
                    NotificationManager.IMPORTANCE_NONE) != enabled) delay(50)
        }
    }

    private fun findChannelSwitch(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isCheckable && node.className?.contains("Switch") == true) return node
        for (i in 0 until node.childCount) {
            node.getChild(i)?.let { child -> findChannelSwitch(child)?.let { return it } }
        }
        return null
    }
}
