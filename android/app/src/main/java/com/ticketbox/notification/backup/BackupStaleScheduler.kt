package com.ticketbox.notification.backup

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/** 备份超龄检测的调度器接缝:只决定「什么时候唤醒」,不碰 stale 判定(那在服务端+engine)。 */
interface BackupStaleScheduler {
    /** 注册 / 更新唯一周期 work。冷启动可重复调用(幂等)。 */
    fun ensurePeriodic(context: Context)

    /** 取消 schedule(如登出 / 调试)。 */
    fun cancel(context: Context)
}

/**
 * WorkManager 实现(0046 边界契约 / 镜像
 * [WorkManagerRecurringReminderScheduler][com.ticketbox.notification.recurring.WorkManagerRecurringReminderScheduler]):
 *
 * - 唯一周期 work [PERIODIC_WORK_NAME],24h + 6h flex(stale 阈值 48h,日级检查频率足够;
 *   不承诺准点,只承诺「有机会提醒」)。
 * - [NetworkType.CONNECTED] 约束:要打后端 status/private。
 * - [ExistingPeriodicWorkPolicy.UPDATE] 幂等,app 升级改 interval 时换新。
 * - 无 one-time 加速入口(与 recurring 不同):备份超龄没有「用户刚操作完想立即看」的场景,
 *   周期 tick 足够;要加时镜像 recurring 的 enqueueOnce 形态。
 * - 不引入 exact alarm / foreground service / boot receiver / 常驻进程(0046 Non-goals)。
 */
class WorkManagerBackupStaleScheduler(
    private val workManagerProvider: (Context) -> WorkManager = { context ->
        WorkManager.getInstance(context)
    },
) : BackupStaleScheduler {

    override fun ensurePeriodic(context: Context) {
        workManagerProvider(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            buildPeriodicRequest(),
        )
    }

    override fun cancel(context: Context) {
        workManagerProvider(context).cancelUniqueWork(PERIODIC_WORK_NAME)
    }

    companion object {
        /** 唯一 work 名(public:测试断言同一常量)。 */
        const val PERIODIC_WORK_NAME = "ticketbox.backup.stale.periodic"

        /** 过滤本功能 work 的 tag。 */
        const val TAG_BACKUP_STALE = "ticketbox.backup.stale"

        /** 日级 cadence(stale 阈值 48h,24h 检查足够),镜像 recurring 的取值理由。 */
        const val REPEAT_INTERVAL_HOURS: Long = 24

        /** flex 窗口,让 OS 在窗口内择机批处理省电。 */
        const val FLEX_INTERVAL_HOURS: Long = 6

        /** 纯构造:24h period + 6h flex + CONNECTED + tag。SchedulerTest 断言其 workSpec。 */
        fun buildPeriodicRequest(): PeriodicWorkRequest =
            PeriodicWorkRequestBuilder<BackupStaleWorker>(
                REPEAT_INTERVAL_HOURS,
                TimeUnit.HOURS,
                FLEX_INTERVAL_HOURS,
                TimeUnit.HOURS,
            )
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build(),
                )
                .addTag(TAG_BACKUP_STALE)
                .build()
    }
}
