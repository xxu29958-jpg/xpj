package com.ticketbox.notification.budget

import android.content.Context
import androidx.core.content.edit

/**
 * 跨进程重启的「已提醒」去重存储（镜像 recurring 的
 * [com.ticketbox.notification.recurring.RecurringReminderStore]，更窄）。
 *
 * 与通知栏 tag 的分工一致：`NotificationManager.notify(tag, id)` 的 tag 只控制通知栏覆盖，
 * 不能阻止下一次检测再发同一提醒——那需要本 store 记住 sent-key。
 *
 * 无 prune：key 是月级（[budgetOverspendSentKey]，账本 × 月各一条），一年一个账本只长 12 条，
 * 无界保留可忽略；要加清理时镜像 recurring store 的 prune 形态。
 */
interface BudgetOverspendStore {
    fun wasSent(key: String): Boolean

    fun markSent(key: String)
}

/**
 * SharedPreferences 实现。独立 prefs 文件（与设置 store 的 `ticketbox_settings`、recurring 的
 * `ticketbox_recurring_reminders` 分开），值不重要，key 存在即「已提醒」。
 */
class SharedPrefsBudgetOverspendStore(
    context: Context,
) : BudgetOverspendStore {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun wasSent(key: String): Boolean = prefs.contains(key)

    override fun markSent(key: String) {
        prefs.edit { putBoolean(key, true) }
    }

    companion object {
        /** 独立 prefs 文件，专放预算超支 sent-key。 */
        const val PREFS_NAME = "ticketbox_budget_overspend"
    }
}
