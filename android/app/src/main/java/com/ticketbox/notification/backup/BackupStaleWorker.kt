package com.ticketbox.notification.backup

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CancellationException

/**
 * 把一次备份超龄检测交给 [BackupStaleEngine] 的 worker(0046 边界契约 / 镜像
 * [RecurringReminderWorker][com.ticketbox.notification.recurring.RecurringReminderWorker])。
 *
 * Worker 只做调度边界:取 engine、调 [BackupStaleEngine.checkAndNotify]、把 outcome 映射成
 * WorkManager [Result]。**不**判 stale、不拼 sent-key、不维护「已提醒」——那些在纯层。
 * reach into [TicketboxApplication.container] 沿用 outbox / recurring worker 的
 * runtime-lookup 模式(手写 DI,WorkerFactory 更重)。
 *
 * doWork 契约:Success(含各类 skipped)→ success;TransientFailure → retry(退避);
 * container 未就绪 → retry;engine 意外抛 → retry 而非 FAILURE 永久压制。
 */
class BackupStaleWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as? TicketboxApplication)?.container
            ?: run {
                Log.w(TAG, "AppContainer not yet ready; deferring backup stale check")
                return Result.retry()
            }
        return runCheck(
            logWarning = { message, error -> Log.w(TAG, message, error) },
        ) { container.backupStaleEngine.checkAndNotify() }
    }

    companion object {
        const val TAG = "BackupStaleWorker"

        /**
         * 跑 [check] 并映射成 WorkManager [Result]。[check] / [logWarning] 注入保证纯 JVM
         * 可测(镜像 recurring worker 的两个接缝;直接调 Log.w 会在纯 JVM 测试触发未 mock 桩)。
         */
        internal suspend fun runCheck(
            logWarning: (String, Throwable) -> Unit = { _, _ -> },
            check: suspend () -> BackupStaleRunOutcome,
        ): Result {
            val outcome: BackupStaleRunOutcome = try {
                check()
            } catch (e: CancellationException) {
                // 让取消正常传播,WorkManager 不计入退避周期(与 outbox / recurring worker 同)。
                throw e
            } catch (e: Exception) {
                // engine 级意外故障(source 失败已转 TransientFailure,不应到这);retry 而非永久压制。
                logWarning("checkAndNotify threw, will retry", e)
                return Result.retry()
            }
            return when (outcome) {
                is BackupStaleRunOutcome.Success -> Result.success()
                is BackupStaleRunOutcome.TransientFailure -> Result.retry()
            }
        }
    }
}
