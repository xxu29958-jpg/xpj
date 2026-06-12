package com.ticketbox.notification.recurring

import androidx.work.ListenableWorker.Result
import com.ticketbox.notification.recurring.RecurringReminderWorker.WorkerResult
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * ADR-0046 Slice 5：[RecurringReminderWorker] 的 outcome → WorkManager Result 映射（Confirmation
 * 「Worker tests」照单）。不直接跑 Android 绑定的 doWork（那只是 [classify] 一行 +
 * [com.ticketbox.TicketboxApplication.container] 查找；为这一个查找引 Robolectric 不划算，
 * 与 outbox worker 同处理）——container-not-ready 的 retry 分支在 doWork 内，属该接缝（报告言明）。
 */
class RecurringReminderWorkerTest {

    @Test
    fun successOutcomeClassifiesToSuccess() {
        assertEquals(
            WorkerResult.SUCCESS,
            RecurringReminderWorker.classify(RecurringReminderRunOutcome.EMPTY_SUCCESS),
        )
    }

    @Test
    fun successWithSentAndSkippedStillSuccess() {
        // 单条 skipped notification 不升级成 worker failure：含 skippedDispatch 的 Success 仍 SUCCESS。
        val outcome = RecurringReminderRunOutcome.Success(
            scanned = 3, due = 2, sent = 1, skippedAlreadySent = 0, skippedDispatch = 1,
        )
        assertEquals(WorkerResult.SUCCESS, RecurringReminderWorker.classify(outcome))
    }

    @Test
    fun transientFailureClassifiesToRetry() {
        assertEquals(
            WorkerResult.RETRY,
            RecurringReminderWorker.classify(RecurringReminderRunOutcome.TransientFailure("io")),
        )
    }

    @Test
    fun runCheckMapsSuccessToResultSuccess() = runTest {
        val result = RecurringReminderWorker.runCheck {
            RecurringReminderRunOutcome.Success(
                scanned = 1, due = 1, sent = 1, skippedAlreadySent = 0, skippedDispatch = 0,
            )
        }
        assertEquals(Result.success(), result)
    }

    @Test
    fun runCheckMapsTransientFailureToResultRetry() = runTest {
        val result = RecurringReminderWorker.runCheck {
            RecurringReminderRunOutcome.TransientFailure("offline")
        }
        assertEquals(Result.retry(), result)
    }

    @Test
    fun runCheckWrapsEngineFaultAsRetry() = runTest {
        // engine 级意外异常（不应发生）→ retry 让 OS 退避，而非永久 FAILURE。
        val result = RecurringReminderWorker.runCheck {
            throw RuntimeException("unexpected engine fault")
        }
        assertEquals(Result.retry(), result)
    }

    @Test
    fun runCheckRethrowsCancellation() = runTest {
        // 取消必须传播，不被吞成 retry（WorkManager 不计退避周期）。
        assertFailsWith<CancellationException> {
            RecurringReminderWorker.runCheck {
                throw CancellationException("cancelled")
            }
        }
    }
}
