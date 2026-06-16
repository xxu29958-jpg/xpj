package com.ticketbox.notification

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class TicketboxNotificationListenerService : NotificationListenerService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val draftDeduper = NotificationDraftDeduper()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val container = (application as? TicketboxApplication)?.container ?: return
        val preferences = container.settingsStore.notificationPreferences()
        if (!preferences.autoCaptureEnabled) return
        if (!container.settingsStore.isBound()) return
        if (!container.expenseRepository.canModifyLedger()) return
        val ledgerIdAtPost = container.expenseRepository.currentActiveLedgerId()
            ?.takeIf { it.isNotBlank() }
            ?: return

        val draft = PaymentNotificationParser.parse(sbn.toSnapshot()) ?: return
        // 去重按**这条通知的系统身份**（sbn.key），不是按内容——见 NotificationDraftDeduper。
        val notificationKey = sbn.key
        if (!draftDeduper.tryReserve(draft, notificationKey)) return

        serviceScope.launch {
            val result = container.expenseRepository.createNotificationDraft(
                draft,
                expectedLedgerId = ledgerIdAtPost,
            )
            if (result.isFailure) {
                draftDeduper.release(draft, notificationKey)
            }
            // 通知闭环 PR-1：草稿建好后按「待确认提醒/大额提醒」开关发系统通知。
            result.onSuccess { created -> container.notifier.onDraftCreated(created) }
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

}
