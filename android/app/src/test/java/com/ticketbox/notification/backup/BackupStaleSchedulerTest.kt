package com.ticketbox.notification.backup

import androidx.work.NetworkType
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import java.util.concurrent.TimeUnit

/**
 * [WorkManagerBackupStaleScheduler.buildPeriodicRequest] 的纯 JVM 断言(镜像
 * RecurringReminderSchedulerTest):24h+6h flex、CONNECTED 约束、tag、worker 类。
 * WorkRequest/WorkSpec 是普通 JVM 对象,无需 Android 设备。
 */
class BackupStaleSchedulerTest {

    @Test
    fun periodicRequestPinsDailyCadenceConnectedConstraintAndWorker() {
        val request = WorkManagerBackupStaleScheduler.buildPeriodicRequest()
        val spec = request.workSpec
        assertEquals(
            TimeUnit.HOURS.toMillis(WorkManagerBackupStaleScheduler.REPEAT_INTERVAL_HOURS),
            spec.intervalDuration,
        )
        assertEquals(
            TimeUnit.HOURS.toMillis(WorkManagerBackupStaleScheduler.FLEX_INTERVAL_HOURS),
            spec.flexDuration,
        )
        assertEquals(NetworkType.CONNECTED, spec.constraints.requiredNetworkType)
        assertEquals(BackupStaleWorker::class.java.name, spec.workerClassName)
        assertTrue(WorkManagerBackupStaleScheduler.TAG_BACKUP_STALE in request.tags)
    }

    @Test
    fun sentKeyIsDayGrained() {
        assertEquals("v1:backup:2026-06-13", backupStaleSentKey(java.time.LocalDate.of(2026, 6, 13)))
        assertEquals("v1:backup:2026-06-14", backupStaleSentKey(java.time.LocalDate.of(2026, 6, 14)))
    }
}
