package com.ticketbox.notification.recurring

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequest
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

/**
 * ADR-0046 Slice 5 / Contract 1 / Contract 9：固定支出提醒的调度器接缝。
 *
 * scheduler 只决定「什么时候唤醒」，不碰 due / overdue 规则（那在 policy / engine）。
 */
interface RecurringReminderScheduler {
    /** 注册 / 更新唯一周期 work。冷启动可重复调用（幂等）。 */
    fun ensurePeriodic(context: Context)

    /** 加速触发：enqueue 一次 one-time 检查（同走 [RecurringReminderWorker] → 同一 engine）。 */
    fun enqueueOnce(context: Context)

    /** 取消两条 schedule（如登出 / 调试）。 */
    fun cancel(context: Context)
}

/**
 * WorkManager 实现（ADR-0046 WorkManager contract）：
 *
 * - 唯一周期 work [PERIODIC_WORK_NAME]，tag [TAG_RECURRING]。
 * - [NetworkType.CONNECTED] 约束：离线时 OS 缓冲该 tick，联网即触发（手机需可达后端）。
 * - 默认 24h 重复 + 6h flex——**不继承** outbox 的 15min heartbeat（Contract 9：日级窗口，不是 outbox 级）。
 *   15min 只是 WorkManager 的系统下限，不是本功能合理默认；本功能只承诺「有机会提醒」，不承诺准点。
 * - [ensurePeriodic] 用 [ExistingPeriodicWorkPolicy.UPDATE]：幂等，且 app 升级改了 interval/flex 时换新。
 * - [enqueueOnce] 用 [ExistingWorkPolicy.KEEP]：连发去重（开关打开 + 刷新列表等多入口触发不堆叠）。
 * - 不引入 AlarmManager 精确闹钟 / foreground service / boot receiver / 常驻进程（ADR Non-goals）。
 *
 * [workManagerProvider] 接缝镜像 outbox scheduler：注入便于（未来）替换；request 构造拆成纯函数
 * [buildPeriodicRequest] / [buildOneTimeRequest]，让 SchedulerTest 在纯 JVM 断言 interval / flex /
 * network 约束 / tag / worker 类（WorkRequest / WorkSpec 是普通 JVM 对象，无需 Android 设备）。
 */
class WorkManagerRecurringReminderScheduler(
    private val workManagerProvider: (Context) -> WorkManager = { context ->
        WorkManager.getInstance(context)
    },
) : RecurringReminderScheduler {

    override fun ensurePeriodic(context: Context) {
        workManagerProvider(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            buildPeriodicRequest(),
        )
    }

    override fun enqueueOnce(context: Context) {
        workManagerProvider(context).enqueueUniqueWork(
            ONE_TIME_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            buildOneTimeRequest(),
        )
    }

    override fun cancel(context: Context) {
        val wm = workManagerProvider(context)
        wm.cancelUniqueWork(PERIODIC_WORK_NAME)
        wm.cancelUniqueWork(ONE_TIME_WORK_NAME)
    }

    companion object {
        /** 唯一 work 名（public：测试断言同一常量；未来维护脚本可寻址）。 */
        const val PERIODIC_WORK_NAME = "ticketbox.recurring.reminders.periodic"
        const val ONE_TIME_WORK_NAME = "ticketbox.recurring.reminders.one_shot"

        /** 过滤本功能 work 的 tag。 */
        const val TAG_RECURRING = "ticketbox.recurring.reminders"

        /** ADR Contract 9：日级 cadence，不是 outbox 的 15min。 */
        const val REPEAT_INTERVAL_HOURS: Long = 24

        /** ADR Contract 9：flex 窗口，让 OS 在窗口内择机批处理省电。 */
        const val FLEX_INTERVAL_HOURS: Long = 6

        private fun connectedConstraints(): Constraints =
            Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

        /** 纯构造：24h period + 6h flex + CONNECTED + tag。SchedulerTest 断言其 workSpec。 */
        fun buildPeriodicRequest(): PeriodicWorkRequest =
            PeriodicWorkRequestBuilder<RecurringReminderWorker>(
                REPEAT_INTERVAL_HOURS,
                TimeUnit.HOURS,
                FLEX_INTERVAL_HOURS,
                TimeUnit.HOURS,
            )
                .setConstraints(connectedConstraints())
                .addTag(TAG_RECURRING)
                .build()

        /** 纯构造：one-time 加速检查，同 CONNECTED + tag。 */
        fun buildOneTimeRequest(): OneTimeWorkRequest =
            OneTimeWorkRequestBuilder<RecurringReminderWorker>()
                .setConstraints(connectedConstraints())
                .addTag(TAG_RECURRING)
                .build()
    }
}
