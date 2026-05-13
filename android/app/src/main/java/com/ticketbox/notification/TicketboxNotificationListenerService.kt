package com.ticketbox.notification

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.ticketbox.TicketboxApplication
import com.ticketbox.domain.model.NotificationDraft
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class TicketboxNotificationListenerService : NotificationListenerService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val recentDraftKeys = LinkedHashMap<String, Long>()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val container = (application as? TicketboxApplication)?.container ?: return
        val preferences = container.settingsStore.notificationPreferences()
        if (!preferences.autoCaptureEnabled) return
        if (!container.settingsStore.isBound()) return
        if (!container.expenseRepository.canModifyLedger()) return

        val draft = PaymentNotificationParser.parse(sbn.toSnapshot()) ?: return
        if (shouldSkipRecentDraft(draft)) return

        serviceScope.launch {
            container.expenseRepository.createNotificationDraft(draft)
        }
    }

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun StatusBarNotification.toSnapshot(): PaymentNotificationSnapshot {
        val extras = notification.extras
        return PaymentNotificationSnapshot(
            packageName = packageName,
            title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString(),
            text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString(),
            bigText = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString(),
            subText = extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString(),
            postTimeMillis = postTime,
        )
    }

    private fun shouldSkipRecentDraft(draft: NotificationDraft): Boolean {
        val now = System.currentTimeMillis()
        val key = listOf(
            draft.source.apiValue,
            draft.amountCents?.toString().orEmpty(),
            draft.merchant.orEmpty(),
            draft.expenseTime.orEmpty().take(16),
        ).joinToString("|")
        synchronized(recentDraftKeys) {
            val iterator = recentDraftKeys.entries.iterator()
            while (iterator.hasNext()) {
                if (now - iterator.next().value > RECENT_DRAFT_TTL_MS) {
                    iterator.remove()
                }
            }
            if (recentDraftKeys.containsKey(key)) return true
            recentDraftKeys[key] = now
            return false
        }
    }

    private companion object {
        const val RECENT_DRAFT_TTL_MS = 30 * 60 * 1000L
    }
}
