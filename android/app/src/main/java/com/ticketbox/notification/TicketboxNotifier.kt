package com.ticketbox.notification

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.annotation.StringRes
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
 * 一条系统通知的纯数据规格（零 Android 依赖，单测直测）：决定 channel、标题/正文/
 * 锁屏 public 脱敏文案各用哪个字符串资源、format-arg 是什么。Android 绑定层（[TicketboxNotifier.publish]）
 * 拿到这个规格后再 `getString` 解析、组装 [NotificationCompat]。
 *
 * 把「用哪个资源 + 传哪些 arg」抽成可测的纯结构，是因为本模块无 Robolectric：
 * 标题 format-arg（大额带商家+金额）、锁屏 public 用脱敏资源、action 存在性这些断言
 * 都落在资源 id / arg 层，不需要真 Context。镜像 PR-1 把 [decideDraftNotification]
 * 抽成纯函数的同一思路。
 *
 * @property channelId 机器串 channel（不资源化）。
 * @property titleRes / [titleArgs] 通知标题资源 + 占位符实参。
 * @property bodyRes / [bodyArgs] 通知正文资源 + 占位符实参。
 * @property publicSummaryRes 锁屏 public 版正文（脱敏、无 arg）。
 * @property actionLabelRes「去核对」action 按钮文案（进待确认页）。
 */
data class NotificationContentSpec(
    val channelId: String,
    @StringRes val titleRes: Int,
    val titleArgs: List<String>,
    @StringRes val bodyRes: Int,
    val bodyArgs: List<String>,
    @StringRes val publicSummaryRes: Int,
    @StringRes val actionLabelRes: Int,
)

/**
 * 纯 JVM 构造草稿/大额通知的内容规格。金额/商家已由调用方格式化为字符串传入，
 * 故本函数零 Android 依赖、可直测。
 *
 * - [DraftNotificationDecision.LARGE]：alerts channel，标题口语化带商家+本位币金额，
 *   正文按是否外币选带原币变体；锁屏 public 用待确认脱敏摘要。
 * - [DraftNotificationDecision.DRAFT]：drafts channel，标题陈述「已记一笔待确认」，
 *   正文同上；public 同上。
 *
 * 注：调用方应只在 decision 为 DRAFT/LARGE 时调用（NONE 不出通知）；传 NONE 视为编程错误。
 */
fun draftNotificationContentSpec(
    decision: DraftNotificationDecision,
    merchant: String,
    homeAmount: String,
    originalAmount: String?,
): NotificationContentSpec {
    require(decision != DraftNotificationDecision.NONE) {
        "draftNotificationContentSpec 不接受 NONE：NONE 应在上游短路，不出通知。"
    }
    val isLarge = decision == DraftNotificationDecision.LARGE
    val bodyRes = if (originalAmount != null) {
        R.string.notification_draft_created_body_with_original
    } else {
        R.string.notification_draft_created_body
    }
    val bodyArgs = if (originalAmount != null) {
        listOf(merchant, homeAmount, originalAmount)
    } else {
        listOf(merchant, homeAmount)
    }
    return NotificationContentSpec(
        channelId = if (isLarge) TicketboxNotifier.CHANNEL_ALERTS else TicketboxNotifier.CHANNEL_DRAFTS,
        titleRes = if (isLarge) R.string.notification_large_amount_title else R.string.notification_draft_created_title,
        // 大额标题「这笔有点大：%1$s %2$s」带商家+金额；草稿标题无 arg。
        titleArgs = if (isLarge) listOf(merchant, homeAmount) else emptyList(),
        bodyRes = bodyRes,
        bodyArgs = bodyArgs,
        publicSummaryRes = R.string.notification_public_draft_summary,
        actionLabelRes = R.string.notification_action_review,
    )
}

/**
 * 纯 JVM 构造固定支出（recurring）提醒的内容规格。标题带固定支出名/商家，
 * 正文「只做提醒，核对后才会入账。」，锁屏 public 用固定支出脱敏摘要。
 */
fun recurringNotificationContentSpec(merchant: String): NotificationContentSpec =
    NotificationContentSpec(
        channelId = TicketboxNotifier.CHANNEL_RECURRING,
        titleRes = R.string.notification_recurring_due_title,
        titleArgs = listOf(merchant),
        bodyRes = R.string.notification_recurring_due_body,
        bodyArgs = emptyList(),
        publicSummaryRes = R.string.notification_public_recurring_summary,
        actionLabelRes = R.string.notification_action_review,
    )

/**
 * 通知闭环 PR-1/PR-2：把「通知监听 → 待确认草稿」「固定支出到期」的结果按设置页提醒开关
 * （待确认提醒 / 大额提醒 / 固定支出提醒）转成系统通知。NLS 与 App 同进程，进程内直发。
 *
 * - 决策交给顶层纯函数（[decideDraftNotification] / [draftNotificationContentSpec] /
 *   [recurringNotificationContentSpec]，可单测）；本类只做 Android 绑定：读 [TicketboxSettingsStore]
 *   开关、[NotificationManagerCompat.areNotificationsEnabled] 守卫、惰性建 channel、把内容规格
 *   解析成 [NotificationCompat] 并发出。
 * - 锁屏 public 版（[NotificationCompat.Builder.setPublicVersion]）只放脱敏摘要，不带商家/金额。
 * - 每条通知带「去核对」action（进待确认页），与 contentIntent 同目标，给锁屏一个快捷入口。
 * - 正文金额走 ui/components/Formatters 的 [formatAmount]/[formatMinorAmount]，不散写 ÷100。
 *
 * PR-2 降级说明（固定支出提醒判定源）：channel + 文案 + [onRecurringDue] 出口已就绪，但**没有
 * 自动触发点**——客户端当前只有 NLS（按支付通知逐条触发）和 outbox drain worker（只重放排队
 * 变更），**没有**「周期扫描本月 active recurring item、判断预期窗口已到且未匹配」的调度源。
 * 可靠实现需要 WorkManager 周期任务 + 本地去重存储 + 同步钩子，属新后台任务子系统（§13「当前
 * 阶段不做」，要做先开 ADR）。故本 PR 不硬造一个不可靠的判定，把检测接缝留作 TODO，见
 * [onRecurringDue] 上方注释。
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
        val spec = draftNotificationContentSpec(
            decision = decision,
            merchant = merchantOrFallback(expense),
            homeAmount = formatAmount(expense.homeAmountCents ?: expense.amountCents, expense.homeCurrency),
            originalAmount = originalAmountOrNull(expense),
        )
        publish(spec, dedupeTag = expense.publicId)
    }

    /**
     * 固定支出（recurring）到期提醒出口。判定本身（哪条 recurring item 该提醒、是否已提醒过）
     * 不在客户端：见类注释「PR-2 降级说明」。本方法仅在「固定支出提醒」开关开 + 系统通知允许时
     * 出一条提醒，留给未来的检测调度源（WorkManager 周期任务 / 同步钩子，需先开 ADR）调用。
     *
     * TODO(notif-loop): 接入固定支出到期检测调度源后调用本方法。检测源需自带去重（同一 item
     *  同一预期窗口只提醒一次），本方法不负责去重判定，只负责按开关出通知。
     *
     * @param merchant 固定支出名 / 商家，进标题占位符。
     * @param dedupeTag 同一提醒的去重 tag（同 tag 覆盖、不同 tag 各保留一条）。
     */
    fun onRecurringDue(merchant: String, dedupeTag: String) {
        val preferences = settingsStore.notificationPreferences()
        if (!preferences.recurringReminders) return
        if (!NotificationManagerCompat.from(appContext).areNotificationsEnabled()) return
        val resolved = merchant.trim().takeIf { it.isNotEmpty() }
            ?: appContext.getString(R.string.notification_draft_created_merchant_missing)
        publish(recurringNotificationContentSpec(resolved), dedupeTag = dedupeTag)
    }

    private fun publish(spec: NotificationContentSpec, dedupeTag: String) {
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
        val reviewIntent = reviewPendingIntent()
        // 锁屏 public 版：只带脱敏摘要 + 同一「去核对」action，不带商家/金额。
        val publicVersion = NotificationCompat.Builder(appContext, spec.channelId)
            .setSmallIcon(R.drawable.ic_notification_receipt)
            .setContentTitle(appContext.getString(R.string.app_name))
            .setContentText(appContext.getString(spec.publicSummaryRes))
            .setContentIntent(reviewIntent)
            .addAction(0, appContext.getString(spec.actionLabelRes), reviewIntent)
            .setAutoCancel(true)
            .build()
        val notification = NotificationCompat.Builder(appContext, spec.channelId)
            .setSmallIcon(R.drawable.ic_notification_receipt)
            .setContentTitle(appContext.getString(spec.titleRes, *spec.titleArgs.toTypedArray()))
            .setContentText(appContext.getString(spec.bodyRes, *spec.bodyArgs.toTypedArray()))
            .setContentIntent(reviewIntent)
            .addAction(0, appContext.getString(spec.actionLabelRes), reviewIntent)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion)
            .setAutoCancel(true)
            .build()
        // tag=去重键：同一草稿/提醒覆盖，不同的各自保留一条。
        manager.notify(dedupeTag, DRAFT_NOTIFICATION_ID, notification)
    }

    private fun merchantOrFallback(expense: Expense): String =
        expense.merchant?.trim()?.takeIf { it.isNotEmpty() }
            ?: appContext.getString(R.string.notification_draft_created_merchant_missing)

    private fun originalAmountOrNull(expense: Expense): String? =
        expense.originalAmountMinor
            ?.takeIf { expense.originalCurrencyCode != expense.homeCurrency }
            ?.let { formatMinorAmount(it, expense.originalCurrencyCode) }

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
                NotificationChannelCompat.Builder(CHANNEL_RECURRING, NotificationManagerCompat.IMPORTANCE_DEFAULT)
                    .setName(appContext.getString(R.string.notification_channel_recurring_name))
                    .build(),
            ),
        )
    }

    /** 「去核对」/ 通知点击：进 App（待确认页是首屏入口）。immutable 满足 API 31+ 要求。 */
    private fun reviewPendingIntent(): PendingIntent {
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

    internal companion object {
        const val CHANNEL_DRAFTS = "ticketbox.drafts"
        const val CHANNEL_ALERTS = "ticketbox.alerts"
        const val CHANNEL_RECURRING = "ticketbox.recurring"
        const val DRAFT_NOTIFICATION_ID = 1
    }
}
