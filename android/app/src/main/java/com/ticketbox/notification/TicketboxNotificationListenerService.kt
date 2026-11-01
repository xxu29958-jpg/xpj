package com.ticketbox.notification

import android.app.Notification
import android.content.ComponentName
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.ticketbox.TicketboxApplication
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.NotificationCaptureRepository
import com.ticketbox.data.repository.NotificationSnapshotDelivery
import com.ticketbox.data.repository.logNetworkWarning
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class TicketboxNotificationListenerService : NotificationListenerService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var captureTail: kotlinx.coroutines.Job? = null

    override fun onListenerConnected() {
        super.onListenerConnected()
        // Reuse the original delivery identity; reconnecting is not a new payment.
        activeNotifications?.forEach(::onNotificationPosted)
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        requestRebind(ComponentName(this, TicketboxNotificationListenerService::class.java))
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val container = (application as? TicketboxApplication)?.container ?: return
        val preferences = container.settingsStore.notificationPreferences()
        if (!preferences.autoCaptureEnabled) return
        if (!container.expenseRepository.canModifyLedger()) return
        val bindingAtPost = container.expenseRepository.captureDeferredLedgerBinding()
            ?: return

        // 隐私边界（codex P2）：非白名单包**在读正文前**就退出——`toSnapshot()` 会读 EXTRA_TITLE/TEXT/
        // BIG_TEXT/SUB_TEXT，必须先按包名过滤，否则非白名单 App 的通知正文仍被读进快照（parse() 内的同款
        // gate 太晚，只挡了正则扫描、没挡正文读取）。
        if (!PaymentNotificationParser.isCandidatePackage(sbn.packageName)) return

        // 统一分类器：一条通知分类成消费 / 还款 / 忽略（§杠杆③ 修双计——含「还款」措辞不再落支出）。
        val cards = PaymentNotificationParser.parseCards(sbn.toSnapshot())
        if (cards.isEmpty()) return
        val notificationKey = notificationIdentityKey(sbn.key, sbn.postTime)
        val delivery = NotificationSnapshotDelivery(notificationIdentityKey(sbn.key, 0), notificationKey, sbn.postTime)
        enqueueSourceChange {
            acceptNotificationBatch(container.notificationCaptureRepository, container.settingsStore,
                cards, bindingAtPost, delivery)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        if (!PaymentNotificationParser.isCandidatePackage(sbn.packageName)) return
        val repository = (application as? TicketboxApplication)?.container?.notificationCaptureRepository ?: return
        enqueueSourceChange {
            repository.closeSnapshot(notificationIdentityKey(sbn.key, 0), notificationIdentityKey(sbn.key, sbn.postTime))
                .onFailure { logNetworkWarning("notification_snapshot_close_failed", it) }
        }
    }

    private fun enqueueSourceChange(action: suspend () -> Unit) {
        val previous = captureTail
        captureTail = serviceScope.launch(start = CoroutineStart.UNDISPATCHED) {
            // A service disconnect cannot cancel a started local acceptance. No network IO is in this block.
            withContext(NonCancellable + Dispatchers.IO) {
                previous?.join()
                action()
            }
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
            textLines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.map { it.toString() }.orEmpty(),
        )
    }
}

internal suspend fun acceptNotificationBatch(repository: NotificationCaptureRepository, settingsStore: TicketboxSettingsStore,
    cards: List<ParsedNotificationCard>, binding: LogicalSessionBinding, delivery: NotificationSnapshotDelivery) {
    repository.acceptSnapshot(cards, binding, delivery).onFailure { error ->
        val scope = notificationCaptureFailureScope(binding)
        logNetworkWarning("notification_capture_admission_failed scope=$scope", error)
        settingsStore.recordNotificationCaptureFailure(scope)
    }
}

/** The OS delivery has no interactive caller to consume an admission failure. Keep only a reconciliation reminder. */
internal suspend fun acceptNotificationCapture(
    repository: NotificationCaptureRepository,
    settingsStore: TicketboxSettingsStore,
    result: PaymentNotificationResult,
    binding: LogicalSessionBinding,
    notificationKey: String,
) {
    repository.accept(result, binding, notificationKey).onFailure { error ->
        val scope = notificationCaptureFailureScope(binding)
        logNetworkWarning("notification_capture_admission_failed scope=$scope", error)
        settingsStore.recordNotificationCaptureFailure(scope)
    }
}
