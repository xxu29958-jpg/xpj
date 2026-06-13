package com.ticketbox.notification.backup

import android.content.Context
import androidx.core.content.edit
import java.time.LocalDate

/**
 * 备份超龄提醒的日级 sent-key:`v1:backup:{localDate}`——同一天最多一响,
 * 次日仍 stale 则再响(备份链断是要催的持续事件,与预算的「一月一响」粒度不同)。
 * 修复后(stale=false)不发,旧 key 自然失效,无需清理。
 */
fun backupStaleSentKey(today: LocalDate): String = "v1:backup:$today"

/**
 * 跨 worker run 的「今天已提醒」去重存储(镜像 recurring / budget store 形态)。
 * 无 prune:key 只在 stale 期间按天增长(断链 30 天=30 条),无界保留可忽略;
 * 要加清理时镜像 recurring store 的 prune 形态。
 */
interface BackupStaleStore {
    fun wasSent(key: String): Boolean

    fun markSent(key: String)
}

/** SharedPreferences 实现。独立 prefs 文件,key 存在即「已提醒」。 */
class SharedPrefsBackupStaleStore(
    context: Context,
) : BackupStaleStore {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override fun wasSent(key: String): Boolean = prefs.contains(key)

    override fun markSent(key: String) {
        prefs.edit { putBoolean(key, true) }
    }

    companion object {
        /** 独立 prefs 文件,专放备份超龄 sent-key。 */
        const val PREFS_NAME = "ticketbox_backup_stale"
    }
}
