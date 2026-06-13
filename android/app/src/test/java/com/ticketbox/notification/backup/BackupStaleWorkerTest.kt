package com.ticketbox.notification.backup

import androidx.work.ListenableWorker
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

/**
 * [BackupStaleWorker.runCheck] 的 outcome → WorkManager Result 映射(镜像
 * RecurringReminderWorkerTest):Success(含 skipped 各态)→ success、TransientFailure →
 * retry、engine 意外抛 → retry 而非 FAILURE 永久压制。
 */
class BackupStaleWorkerTest {

    @Test
    fun successOutcomeMapsToSuccess() = runTest {
        val result = BackupStaleWorker.runCheck {
            BackupStaleRunOutcome.Success(BackupStaleRunOutcome.Detail.SKIPPED_FRESH)
        }
        assertEquals(ListenableWorker.Result.success(), result)
    }

    @Test
    fun transientFailureMapsToRetry() = runTest {
        val result = BackupStaleWorker.runCheck {
            BackupStaleRunOutcome.TransientFailure("IOException")
        }
        assertEquals(ListenableWorker.Result.retry(), result)
    }

    @Test
    fun unexpectedThrowMapsToRetryAndLogs() = runTest {
        var logged = false
        val result = BackupStaleWorker.runCheck(
            logWarning = { _, _ -> logged = true },
        ) {
            error("engine exploded")
        }
        assertEquals(ListenableWorker.Result.retry(), result)
        assertTrue(logged)
    }
}
