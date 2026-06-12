package com.ticketbox.notification.recurring

import androidx.work.NetworkType
import com.ticketbox.data.repository.OutboxScheduler
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0046 Slice 5：[WorkManagerRecurringReminderScheduler] 的 WorkRequest 构造契约
 * （Confirmation「Scheduler tests」照单）。
 *
 * 断言纯构造 [WorkManagerRecurringReminderScheduler.buildPeriodicRequest] /
 * [WorkManagerRecurringReminderScheduler.buildOneTimeRequest] 的 workSpec——WorkRequest / WorkSpec
 * 是普通 JVM 对象，无需 Android 设备（本模块无 Robolectric / 无 WorkManager TestDriver 可在纯 JVM 跑）。
 * 唯一 work 名 + UPDATE/KEEP 语义是常量与 enqueue 调用的字面量，直接钉常量（enqueue 真实调用走
 * WorkManager.getInstance，需设备/初始化，留作接缝，由实机/模拟器与代码评审覆盖——报告言明）。
 */
class RecurringReminderSchedulerTest {

    @Test
    fun periodicRequestUsesConnectedNetworkConstraint() {
        val request = WorkManagerRecurringReminderScheduler.buildPeriodicRequest()
        assertEquals(NetworkType.CONNECTED, request.workSpec.constraints.requiredNetworkType)
    }

    @Test
    fun periodicRequestUsesDayLevelCadenceNotOutboxFifteenMinutes() {
        // ADR Contract 9：24h 周期 + 6h flex，**不**继承 outbox 的 15min heartbeat。
        val request = WorkManagerRecurringReminderScheduler.buildPeriodicRequest()
        assertEquals(
            TimeUnit.HOURS.toMillis(WorkManagerRecurringReminderScheduler.REPEAT_INTERVAL_HOURS),
            request.workSpec.intervalDuration,
        )
        assertEquals(
            TimeUnit.HOURS.toMillis(WorkManagerRecurringReminderScheduler.FLEX_INTERVAL_HOURS),
            request.workSpec.flexDuration,
        )
    }

    @Test
    fun cadenceConstantsAreDayLevelAndDistinctFromOutbox() {
        // 钉字面量：24h / 6h，且严格大于 outbox 的 15min floor——防有人把它「顺手」改回 15min。
        assertEquals(24L, WorkManagerRecurringReminderScheduler.REPEAT_INTERVAL_HOURS)
        assertEquals(6L, WorkManagerRecurringReminderScheduler.FLEX_INTERVAL_HOURS)
        val recurringIntervalMin = WorkManagerRecurringReminderScheduler.REPEAT_INTERVAL_HOURS * 60
        assertTrue(recurringIntervalMin > OutboxScheduler.PERIODIC_INTERVAL_MIN)
    }

    @Test
    fun periodicRequestTargetsRecurringWorkerAndTag() {
        val request = WorkManagerRecurringReminderScheduler.buildPeriodicRequest()
        assertEquals(RecurringReminderWorker::class.java.name, request.workSpec.workerClassName)
        assertTrue(request.tags.contains(WorkManagerRecurringReminderScheduler.TAG_RECURRING))
    }

    @Test
    fun oneTimeRequestUsesConnectedConstraintAndTagAndRecurringWorker() {
        val request = WorkManagerRecurringReminderScheduler.buildOneTimeRequest()
        assertEquals(NetworkType.CONNECTED, request.workSpec.constraints.requiredNetworkType)
        assertEquals(RecurringReminderWorker::class.java.name, request.workSpec.workerClassName)
        assertTrue(request.tags.contains(WorkManagerRecurringReminderScheduler.TAG_RECURRING))
    }

    @Test
    fun uniqueWorkNamesAreStableAndDistinct() {
        // 唯一 work 名一经发布不可改（ensurePeriodic 幂等的根 = 同名 + UPDATE policy）。
        assertEquals(
            "ticketbox.recurring.reminders.periodic",
            WorkManagerRecurringReminderScheduler.PERIODIC_WORK_NAME,
        )
        assertEquals(
            "ticketbox.recurring.reminders.one_shot",
            WorkManagerRecurringReminderScheduler.ONE_TIME_WORK_NAME,
        )
        assertTrue(
            WorkManagerRecurringReminderScheduler.PERIODIC_WORK_NAME !=
                WorkManagerRecurringReminderScheduler.ONE_TIME_WORK_NAME,
        )
        // 与 outbox 的 work 名不同名（不串台、不互相覆盖唯一 work）。
        assertTrue(
            WorkManagerRecurringReminderScheduler.PERIODIC_WORK_NAME != OutboxScheduler.PERIODIC_WORK_NAME,
        )
    }
}
