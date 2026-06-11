package com.ticketbox.notification

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationChannelCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.ticketbox.MainActivity
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.components.formatMinorAmount

/**
 * 草稿创建通知的决策结果。单一枚举返回值本身就是「不双响」保证：
 * 两个开关同时命中时只产出 [LARGE]，不会再叠加一条 [DRAFT]。
 */
enum class DraftNotificationDecision { NONE, DRAFT, LARGE }

/**
 * 大额提醒阈值：50_000 分 = ¥500，本位币（人民币）最小单位。
 *
 * 比较输入是后端汇率换算后的本位币金额（[Expense.homeAmountCents]），
 * 外币票天然按折算后的人民币金额参与比较，无需另设外币阈值。
 * 改阈值时同步改 strings_notifications.xml 里写明「¥500」的大额副标题文案。
 */
const val LARGE_AMOUNT_THRESHOLD_CENTS = 50_000L

/**
 * 纯 JVM 决策函数（零 Android 依赖，单测直测）：草稿创建成功后发哪种系统通知。
 *
 * 规则：
 * - [notificationsAllowed] 为 false（系统通知被关闭/权限未授予）一律 [DraftNotificationDecision.NONE]。
 * - 大额开关开且 [amountCents] 达到 [LARGE_AMOUNT_THRESHOLD_CENTS] → [DraftNotificationDecision.LARGE]，
 *   吞并 DRAFT 不双响（大额提醒本身已含「有新草稿待确认」语义）。
 * - 否则待确认开关开 → [DraftNotificationDecision.DRAFT]。
 * - [amountCents] 为 null 时无从判断大额，只可能 DRAFT。
 *
 * [amountCents] 是本位币（人民币）分，见 [LARGE_AMOUNT_THRESHOLD_CENTS]。
 */
fun decideDraftNotification(
    pendingEnabled: Boolean,
    largeEnabled: Boolean,
    amountCents: Long?,
    notificationsAllowed: Boolean,
): DraftNotificationDecision {
    if (!notificationsAllowed) return DraftNotificationDecision.NONE
    val reachesLargeThreshold = amountCents != null && amountCents >= LARGE_AMOUNT_THRESHOLD_CENTS
    return when {
        largeEnabled && reachesLargeThreshold -> DraftNotificationDecision.LARGE
        pendingEnabled -> DraftNotificationDecision.DRAFT
        else -> DraftNotificationDecision.NONE
    }
}

/**
 * 通知闭环 PR-1：把「通知监听 → 待确认草稿」的成功结果按设置页两个提醒开关
 * （待确认提醒 / 大额提醒）转成系统通知。NLS 与 App 同进程，进程内直发。
 *
 * - 决策交给顶层 [decideDraftNotification]（纯 JVM，可单测）；本类只做 Android 绑定：
 *   读 [TicketboxSettingsStore] 开关、[NotificationManagerCompat.areNotificationsEnabled] 守卫、
 *   惰性建 channel、组装并发出 [NotificationCompat] 通知。
 * - 正文金额走 ui/components/Formatters 的 [formatAmount]/[formatMinorAmount]，不散写 ÷100。
 * - 入参是后端返回的完整领域 [Expense]：外币票（originalCurrencyCode != homeCurrency 且有
 *   originalAmountMinor）正文带原币提示；NLS 解析端（[PaymentNotificationParser]）目前只产
 *   人民币草稿，该分支等后端原币字段出现时自然生效。
 * - 固定支出提醒（recurringReminders）开关在本 PR 不消费，留给后续 PR。
 */
class TicketboxNotifier(
    context: Context,
    private val settingsStore: TicketboxSettingsStore,
) {
    private val appContext = context.applicationContext

    fun onDraftCreated(expense: Expense) {
        val preferences = settingsStore.notificationPreferences()
        val decision = decideDraftNotification(
            pendingEnabled = preferences.pendingDraftReminders,
            largeEnabled = preferences.largeAmountAlerts,
            amountCents = expense.homeAmountCents ?: expense.amountCents,
            notificationsAllowed = NotificationManagerCompat.from(appContext).areNotificationsEnabled(),
        )
        if (decision == DraftNotificationDecision.NONE) return
        publish(decision, expense)
    }

    private fun publish(decision: DraftNotificationDecision, expense: Expense) {
        // API 33+ 的显式权限检查：行为上已被 areNotificationsEnabled() 守卫覆盖
        // （T+ 上未授权即返回 false），这里再查一次是 notify() 的
        // @RequiresPermission(POST_NOTIFICATIONS) lint 契约要求的可识别形态。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                appContext,
                Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val manager = NotificationManagerCompat.from(appContext)
        ensureChannels(manager)
        val isLarge = decision == DraftNotificationDecision.LARGE
        val title = appContext.getString(
            if (isLarge) R.string.notification_large_amount_title else R.string.notification_draft_created_title,
        )
        val notification = NotificationCompat.Builder(appContext, if (isLarge) CHANNEL_ALERTS else CHANNEL_DRAFTS)
            .setSmallIcon(R.drawable.ic_notification_receipt)
            .setContentTitle(title)
            .setContentText(contentBody(expense))
            .setContentIntent(contentIntent())
            .setAutoCancel(true)
            .build()
        // tag=publicId：同一张草稿去重覆盖，不同草稿各自保留一条。
        manager.notify(expense.publicId, DRAFT_NOTIFICATION_ID, notification)
    }

    /** 幂等：channel 已存在时 create 是 no-op（名称变更会被系统采纳）。minSdk=28 ≥ O，无需版本分支。 */
    private fun ensureChannels(manager: NotificationManagerCompat) {
        manager.createNotificationChannelsCompat(
            listOf(
                NotificationChannelCompat.Builder(CHANNEL_DRAFTS, NotificationManagerCompat.IMPORTANCE_DEFAULT)
                    .setName(appContext.getString(R.string.notification_channel_drafts_name))
                    .build(),
                NotificationChannelCompat.Builder(CHANNEL_ALERTS, NotificationManagerCompat.IMPORTANCE_HIGH)
                    .setName(appContext.getString(R.string.notification_channel_alerts_name))
                    .build(),
            ),
        )
    }

    private fun contentBody(expense: Expense): String {
        val merchant = expense.merchant?.trim()?.takeIf { it.isNotEmpty() }
            ?: appContext.getString(R.string.notification_draft_created_merchant_missing)
        val homeAmount = formatAmount(expense.homeAmountCents ?: expense.amountCents, expense.homeCurrency)
        val originalAmount = expense.originalAmountMinor
            ?.takeIf { expense.originalCurrencyCode != expense.homeCurrency }
            ?.let { formatMinorAmount(it, expense.originalCurrencyCode) }
        return if (originalAmount != null) {
            appContext.getString(
                R.string.notification_draft_created_body_with_original,
                merchant,
                homeAmount,
                originalAmount,
            )
        } else {
            appContext.getString(R.string.notification_draft_created_body, merchant, homeAmount)
        }
    }

    private fun contentIntent(): PendingIntent {
        val intent = Intent(appContext, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        return PendingIntent.getActivity(
            appContext,
            0,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    private companion object {
        const val CHANNEL_DRAFTS = "ticketbox.drafts"
        const val CHANNEL_ALERTS = "ticketbox.alerts"
        const val DRAFT_NOTIFICATION_ID = 1
    }
}
