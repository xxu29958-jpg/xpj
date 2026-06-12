package com.ticketbox.notification.recurring

import com.ticketbox.domain.model.RecurringItem
import java.time.LocalDate

/**
 * ADR-0046 Slice 4 engine 一次扫描的结果（Implementation Shape: [RecurringReminderRunOutcome]）。
 *
 * - [Success]：扫描完成（含「开关关 / 未登录 / 列表为空」等 safe-success），worker 映射 Result.success()。
 * - [TransientFailure]：瞬时失败（source 网络 / API 故障），worker 映射 Result.retry()（Contract 8）。
 *
 * 任何失败都不写服务端业务状态、不 mark sent。
 */
sealed interface RecurringReminderRunOutcome {
    data class Success(
        val scanned: Int,
        val due: Int,
        val sent: Int,
        val skippedAlreadySent: Int,
        val skippedDispatch: Int,
    ) : RecurringReminderRunOutcome

    data class TransientFailure(val reason: String) : RecurringReminderRunOutcome

    companion object {
        /** 不发任何提醒、未拉 source（或拉了但零提醒）的安全成功。 */
        val EMPTY_SUCCESS = Success(scanned = 0, due = 0, sent = 0, skippedAlreadySent = 0, skippedDispatch = 0)
    }
}

/**
 * ADR-0046 Slice 4 engine 的运行时上下文：设置开关 / session 前置 / 当天时钟 / 轻量日志。
 * 打包成一个值对象，使 [RecurringReminderEngine] 构造参数 ≤6（detekt LongParameterList）。
 *
 * @property recurringRemindersEnabled 「固定支出提醒」开关现读（关 → engine 不拉 source、不发、不 markSent）。
 * @property sessionReady 已登录 + 有 active ledger + server 地址（否则 safe success；Contract 8/11）。
 * @property today 可注入当天（设备本地日期），便于测试钉边界。
 * @property logWarning 轻量日志注入：单条 item 异常 / source 失败时记 error class，**不记** token /
 *   header / 完整商户明细 / 通知原文（Contract 8）。注入而非直接 android.util.Log 是为了纯 JVM 测试
 *   不触发未 mock 的 Log 桩（与 outbox worker 同思路）。
 */
class RecurringReminderRuntime(
    val recurringRemindersEnabled: () -> Boolean,
    val sessionReady: () -> Boolean,
    val today: () -> LocalDate,
    val logWarning: (String, Throwable?) -> Unit = { _, _ -> },
)

/**
 * ADR-0046 Slice 4 编排核心（Contract 2）：串联 source → policy → store → dispatcher，
 * 但**不拥有 due 规则本身**（那在 [RecurringReminderPolicy]）。
 *
 * Engine 不得：改写服务端 recurring item、创建 pending、确认 expense、把 frequency 转下一次日期、
 * 失败时写业务补偿状态（Contract 2）。失败一律安全降级，不 mark sent（Contract 8）。
 *
 * 四层协作（source / policy / store / dispatcher）显式注入；运行时上下文（设置开关 / session 前置 /
 * 时钟 / 日志）打包成 [RecurringReminderRuntime]，使构造参数 ≤6（detekt LongParameterList）。
 * 全部 Android / IO / 时钟依赖经注入，故 EngineTest 用 fake source / store / dispatcher + 固定 today
 * 直测（本模块无 Robolectric，业务契约必须落纯 JVM 层）。
 *
 * @property source 只读候选来源。
 * @property policy 纯函数 due/overdue 判定。
 * @property store 跨 run 去重。
 * @property dispatcher 通知出口（返回 outcome；只有 SENT 才 markSent）。
 * @property runtime 设置开关 / session 就绪 / 当天 / 日志（见 [RecurringReminderRuntime]）。
 */
class RecurringReminderEngine(
    private val source: RecurringReminderSource,
    private val policy: RecurringReminderPolicy,
    private val store: RecurringReminderStore,
    private val dispatcher: RecurringReminderDispatcher,
    private val runtime: RecurringReminderRuntime,
) {
    /**
     * 一次完整检测：读设置 / session 前置 → 拉 active items → 逐条 policy → 查 store → dispatch →
     * 成功发出后 markSent。返回 [RecurringReminderRunOutcome]。
     */
    suspend fun checkAndNotify(): RecurringReminderRunOutcome {
        if (!runtime.recurringRemindersEnabled()) return RecurringReminderRunOutcome.EMPTY_SUCCESS
        if (!runtime.sessionReady()) return RecurringReminderRunOutcome.EMPTY_SUCCESS

        val items = source.activeItems().getOrElse { error ->
            // source 失败 → 瞬时失败，worker 退避重试，不 mark sent。401/403 在仓库的
            // NetworkErrorHandler 里与网络故障同折叠为 RepositoryException，此处刻意不再
            // 区分（Contract 8 的「session 失效路径」分支）：常见失效态（token 已清）已被
            // sessionReady 前置门拦成 safe-success；存活但被撤销的 token 至多触发
            // WorkManager 有界退避 + 下个 24h 周期，不构成无限 retry。
            runtime.logWarning("recurring source failed: ${error::class.java.simpleName}", error)
            return RecurringReminderRunOutcome.TransientFailure(error::class.java.simpleName)
        }

        return scanItems(items, runtime.today())
    }

    /** 遍历 items 累计计数。单条 item 异常被隔离（跳过 + 轻量日志），不让整轮失败（Contract 8）。 */
    private fun scanItems(items: List<RecurringItem>, todayDate: LocalDate): RecurringReminderRunOutcome.Success {
        val tally = Tally()
        for (item in items) {
            tally.scanned++
            try {
                processItem(item, todayDate, tally)
            } catch (error: Exception) {
                // 防御：policy 本身不抛，但 dispatch 等理论上可能。隔离单条，不污染其它 item。
                runtime.logWarning("recurring item skipped: ${error::class.java.simpleName}", error)
            }
        }
        return tally.toSuccess()
    }

    /** 单条 item：policy 判定 → 已提醒则跳过 → 否则 dispatch → SENT 才 markSent。 */
    private fun processItem(item: RecurringItem, todayDate: LocalDate, tally: Tally) {
        val decision = policy.evaluate(todayDate, item) ?: return
        tally.due++
        if (store.wasSent(decision.key)) {
            tally.skippedAlreadySent++
            return
        }
        when (dispatcher.dispatch(decision)) {
            RecurringReminderDispatchOutcome.SENT -> {
                store.markSent(decision.key)
                tally.sent++
            }
            else -> tally.skippedDispatch++
        }
    }

    /** 可变计数器，仅在一次 [checkAndNotify] 内部使用。 */
    private class Tally {
        var scanned = 0
        var due = 0
        var sent = 0
        var skippedAlreadySent = 0
        var skippedDispatch = 0

        fun toSuccess() = RecurringReminderRunOutcome.Success(
            scanned = scanned,
            due = due,
            sent = sent,
            skippedAlreadySent = skippedAlreadySent,
            skippedDispatch = skippedDispatch,
        )
    }
}
