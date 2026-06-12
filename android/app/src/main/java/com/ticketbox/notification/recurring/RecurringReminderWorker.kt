package com.ticketbox.notification.recurring

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ticketbox.TicketboxApplication
import kotlinx.coroutines.CancellationException

/**
 * ADR-0046 Slice 5 / Contract 1：把一次固定支出提醒检测交给 [RecurringReminderEngine] 的 worker。
 *
 * Worker 只做调度边界（Contract 1）：取 engine、调 [RecurringReminderEngine.checkAndNotify]、
 * 把 engine outcome 映射成 WorkManager [Result]。**不**散写 due/overdue 规则、不拼 sent-key、
 * 不直接判 frequency、不直接维护「已提醒」状态——那些全在纯 Kotlin 可测层。
 *
 * 为什么 reach into [TicketboxApplication.container] 而非构造注入 engine：项目用手写 DI
 * （[com.ticketbox.AppContainer]），WorkManager 默认 WorkerFactory 只认 (Context, WorkerParameters)。
 * 自定义 WorkerFactory 更重，沿用 outbox worker 既有的 runtime-lookup 模式（[com.ticketbox.data.repository.OutboxDrainWorker]）。
 *
 * doWork 契约（Contract 8）：
 *  - engine [RecurringReminderRunOutcome.Success]（含开关关 / 未登录 / 空列表 / 已全部去重）→ [Result.success]。
 *  - engine [RecurringReminderRunOutcome.TransientFailure]（source 网络 / API 故障）→ [Result.retry]（退避）。
 *  - container 未就绪（worker 早于 Application.onCreate）→ [Result.retry]（OS 会在 app 起来后重排）。
 *  - 单条 skipped notification **不**升级为 worker failure（engine 内部已隔离单条）。
 */
class RecurringReminderWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as? TicketboxApplication)?.container
            ?: run {
                Log.w(TAG, "AppContainer not yet ready; deferring recurring reminder check")
                return Result.retry()
            }
        return runCheck(
            logWarning = { message, error -> Log.w(TAG, message, error) },
        ) { container.recurringReminderEngine.checkAndNotify() }
    }

    /** post-check 分类（Implementation Shape 类型微调允许，职责边界不变）。 */
    internal enum class WorkerResult { SUCCESS, RETRY }

    companion object {
        const val TAG = "RecurringReminderWorker"

        /**
         * 跑 [check] 并把 outcome 映射成 WorkManager 等价的 [WorkerResult]。
         *
         * 两个接缝保证纯 JVM 可测（与 outbox worker 同思路）：
         *  - [check] 作为 suspend lambda 注入，解耦 engine 是否 final，且测试可注任意 outcome / 异常。
         *  - [logWarning] 注入：failure 路径上唯一的 Android 副作用，测试默认 no-op，
         *    [doWork] 供真 [android.util.Log] 绑定。直接调 Log.w 会在纯 JVM 测试触发未 mock 的桩异常。
         */
        internal suspend fun runCheck(
            logWarning: (String, Throwable) -> Unit = { _, _ -> },
            check: suspend () -> RecurringReminderRunOutcome,
        ): Result {
            val outcome: RecurringReminderRunOutcome = try {
                check()
            } catch (e: CancellationException) {
                // 让取消正常传播，WorkManager 不计入退避周期（与 outbox worker 同）。
                throw e
            } catch (e: Exception) {
                // engine 级意外故障（不应发生——engine 内部已隔离单条 + source 失败已转 TransientFailure）。
                // 返回 retry 让 OS 退避，而非 FAILURE 永久压制。
                logWarning("checkAndNotify threw, will retry", e)
                return Result.retry()
            }
            return when (classify(outcome)) {
                WorkerResult.SUCCESS -> Result.success()
                WorkerResult.RETRY -> Result.retry()
            }
        }

        /** outcome → WorkerResult：Success 系列 SUCCESS、TransientFailure RETRY。 */
        internal fun classify(outcome: RecurringReminderRunOutcome): WorkerResult =
            when (outcome) {
                is RecurringReminderRunOutcome.Success -> WorkerResult.SUCCESS
                is RecurringReminderRunOutcome.TransientFailure -> WorkerResult.RETRY
            }
    }
}
