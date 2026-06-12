package com.ticketbox.notification.recurring

import android.content.Context
import androidx.core.content.edit
import java.time.LocalDate
import java.time.format.DateTimeParseException

/**
 * ADR-0046 Slice 3 / Contract 5：跨 worker run 的「已提醒」去重存储。
 *
 * 与通知栏 tag 的分工：`NotificationManager.notify(tag, id)` 的 tag 只控制通知栏覆盖，
 * **不能**阻止下一次 worker 再发同一提醒——那需要本 store 记住 sent-key。两者职责分开。
 *
 * key 格式见 [recurringReminderSentKey]。retention 不是业务正确性底座：key 丢失最多导致重复提醒，
 * 不会写错账本，故 [prune] 是可选清理（本实现按 expectedDate 清理远期旧 key，见 impl）。
 */
interface RecurringReminderStore {
    fun wasSent(key: String): Boolean

    fun markSent(key: String)

    /**
     * 清理 expectedDate 早于 [cutoff] 的 key（解析 key 的 expectedDate 段）。
     * 不解析的 key（格式异常 / 旧版本）保守保留，不误删。
     */
    fun prune(cutoff: LocalDate)
}

/**
 * 取 sent-key 的 expectedDate 段（倒数第二段，kind 恒为最后一段——对 ledgerId / itemPublicId
 * 含冒号也稳健）。格式不符 / 不可解析返回 null（prune 据此保守保留，不误删）。
 *
 * 纯函数，独立于任何存储后端：[SharedPrefsRecurringReminderStore] 与测试 in-memory store 共用，
 * 保证两者 prune 语义一致、可在纯 JVM 直测（本模块无 Robolectric，SharedPreferences 取不到）。
 */
fun recurringReminderKeyExpectedDate(key: String): LocalDate? {
    val segments = key.split(":")
    // v1 : ledgerId : itemPublicId : expectedDate : kind —— 至少 5 段。
    if (segments.size < MIN_KEY_SEGMENTS) return null
    val expectedDateSegment = segments[segments.size - 2]
    return try {
        LocalDate.parse(expectedDateSegment)
    } catch (_: DateTimeParseException) {
        null
    }
}

/** `v1:ledger:item:date:kind` 至少 5 段。 */
private const val MIN_KEY_SEGMENTS = 5

/**
 * SharedPreferences 实现（Contract 5 允许 MVP 用 SharedPrefs；未来加 snooze / mute / history 再升 Room）。
 *
 * 存储形态：每个 sent-key 作为一个 `key=true` 条目存进独立 prefs 文件
 * （[PREFS_NAME]，与设置 store 的 `ticketbox_settings` 分开，避免污染）。值不重要，存在即「已提醒」。
 *
 * [prune] 解析每个 sent-key 的 expectedDate 段（倒数第二段，kind 恒为最后一段——对 ledgerId /
 * itemPublicId 含冒号也稳健），早于 cutoff 的删除。解析不出日期的 key 保守保留（不误删刚写入的 key）。
 */
class SharedPrefsRecurringReminderStore(
    context: Context,
) : RecurringReminderStore {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun wasSent(key: String): Boolean = prefs.contains(key)

    override fun markSent(key: String) {
        prefs.edit { putBoolean(key, true) }
    }

    override fun prune(cutoff: LocalDate) {
        val expired = prefs.all.keys.filter { key ->
            val expectedDate = recurringReminderKeyExpectedDate(key) ?: return@filter false
            expectedDate.isBefore(cutoff)
        }
        if (expired.isEmpty()) return
        prefs.edit {
            expired.forEach { remove(it) }
        }
    }

    companion object {
        /** 独立 prefs 文件，与 `ticketbox_settings` 分开存放 sent-key。 */
        const val PREFS_NAME = "ticketbox_recurring_reminders"
    }
}
