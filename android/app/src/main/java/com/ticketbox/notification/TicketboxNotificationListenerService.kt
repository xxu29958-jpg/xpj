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

        // 统一分类器：一条通知分类成消费 / 还款 / 忽略（§杠杆③ 修双计——含「还款」措辞不再落支出）。
        val result = PaymentNotificationParser.parse(sbn.toSnapshot()) ?: return
        // 去重按**这条通知的每次投递身份** = hash(sbn.key | sbn.postTime)：含 postTime,故个别 App 复用同一
        // 通知槽承载第二笔真账(同 sbn.key、新 postTime)时各算一笔(codex P2#1);定长 hash 不触后端长度上限、
        // 原始 key 不离设备(codex P2#2)。本地去重器 + 透传后端幂等键共用同一身份(否则后端按内容去重仍吞单)。
        val notificationKey = notificationIdentityKey(sbn.key, sbn.postTime)
        if (!draftDeduper.tryReserve(result, notificationKey)) return

        serviceScope.launch {
            dispatch(container, result, ledgerIdAtPost, notificationKey)
        }
    }

    /**
     * 把分类结果路由到对应仓库（§1 路由不在回调线程，放协程）。消费走既有 [createNotificationDraft] +
     * 通知闭环；还款走新 `/api/repayment-drafts`（§8 永不自动记账，落 pending 草稿等用户复核选债）。
     * 任一失败都释放去重占位，让下次重发可重试。
     *
     * 还款草稿**不发系统通知**：通知默认关闭、且既有「去核对」通知点击进的是待确认页（无还款复核箱深链），
     * 强发会把用户引到错屏；还款复核箱从「规划」菜单进，与消费草稿落 pending 默认静默同构。还款通知闭环
     * （独立 channel + 深链）是单独后续切片，与预算/备份提醒走过的「通知闭环」分片同理。
     */
    private suspend fun dispatch(
        container: com.ticketbox.AppContainer,
        result: PaymentNotificationResult,
        ledgerIdAtPost: String,
        notificationKey: String,
    ) {
        val outcome = when (result) {
            is PaymentNotificationResult.Expense -> container.expenseRepository.createNotificationDraft(
                result.draft,
                expectedLedgerId = ledgerIdAtPost,
                notificationKey = notificationKey,
            ).onSuccess { created -> container.notifier.onDraftCreated(created) }

            is PaymentNotificationResult.Repayment -> container.repaymentDraftRepository.createDraft(
                result.draft,
                expectedLedgerId = ledgerIdAtPost,
                notificationKey = notificationKey,
            )
        }
        if (outcome.isFailure) {
            draftDeduper.release(result, notificationKey)
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
