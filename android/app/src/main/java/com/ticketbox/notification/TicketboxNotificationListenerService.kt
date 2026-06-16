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

        // 隐私边界（codex P2）：非白名单包**在读正文前**就退出——`toSnapshot()` 会读 EXTRA_TITLE/TEXT/
        // BIG_TEXT/SUB_TEXT，必须先按包名过滤，否则非白名单 App 的通知正文仍被读进快照（parse() 内的同款
        // gate 太晚，只挡了正则扫描、没挡正文读取）。
        if (!PaymentNotificationParser.isCandidatePackage(sbn.packageName)) return

        val draft = PaymentNotificationParser.parse(sbn.toSnapshot()) ?: return
        // 去重按**这条通知的系统身份**（sbn.key）：本地去重器 + 透传到后端幂等键（codex P1，否则后端按内容
        // 去重仍会吞掉同分钟同金额的第二笔真账）。
        val notificationKey = sbn.key
        if (!draftDeduper.tryReserve(draft, notificationKey)) return

        serviceScope.launch {
            val result = container.expenseRepository.createNotificationDraft(
                draft,
                expectedLedgerId = ledgerIdAtPost,
                notificationKey = notificationKey,
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
