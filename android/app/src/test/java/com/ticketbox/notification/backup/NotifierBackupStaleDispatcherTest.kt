package com.ticketbox.notification.backup

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * [NotifierBackupStaleDispatcher]:小时→天折算(72h→"3";向下取整)、无备份(null)透传 null
 * 让 notifier 换文案变体、sent-key 作通知覆盖 tag 透传、outcome 透传。
 * 窄函数接缝注 lambda 直测(本模块无 Robolectric)。
 */
class NotifierBackupStaleDispatcherTest {

    private fun decisionOf(ageHours: Int?) = BackupStaleDecision(
        key = "v1:backup:2026-06-13",
        ageHours = ageHours,
    )

    @Test
    fun convertsAgeHoursToFlooredDaysAndPassesKey() {
        var capturedDays: String? = "unset"
        var capturedTag: String? = null
        val dispatcher = NotifierBackupStaleDispatcher { days, tag ->
            capturedDays = days
            capturedTag = tag
            BackupStaleDispatchOutcome.SENT
        }
        val outcome = dispatcher.dispatch(decisionOf(ageHours = 79))
        assertEquals(BackupStaleDispatchOutcome.SENT, outcome)
        // 79h / 24 = 3(向下取整——「已是 3 天前」宁少勿夸)。
        assertEquals("3", capturedDays)
        assertEquals("v1:backup:2026-06-13", capturedTag)
    }

    @Test
    fun neverBackedUpPassesNullDaysForBodyVariant() {
        var capturedDays: String? = "unset"
        val dispatcher = NotifierBackupStaleDispatcher { days, _ ->
            capturedDays = days
            BackupStaleDispatchOutcome.SKIPPED_DISABLED
        }
        val outcome = dispatcher.dispatch(decisionOf(ageHours = null))
        assertEquals(BackupStaleDispatchOutcome.SKIPPED_DISABLED, outcome)
        assertEquals(null, capturedDays)
    }
}
