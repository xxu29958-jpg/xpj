package com.ticketbox.notification.budget

import com.ticketbox.domain.model.BudgetMonthly
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * 当月预算的**只读**来源。生产接线是 `budgetRepository::monthlyBudget` 的直接透传
 * （fun interface，无适配类）；测试注 lambda。实现禁止任何写。
 */
fun interface BudgetOverspendSource {
    suspend fun monthlyBudget(month: String): Result<BudgetMonthly>
}

/**
 * 检测器的运行时上下文：开关 / active ledger / 当月 / 单调时钟 / 轻量日志。
 * 打包成值对象使 [BudgetOverspendChecker] 构造参数 ≤6（detekt LongParameterList，镜像
 * [RecurringReminderRuntime][com.ticketbox.notification.recurring.RecurringReminderRuntime]）。
 *
 * @property budgetOverspendAlertsEnabled 「预算超支提醒」开关现读（关 → 不拉预算、不发、不 markSent）。
 * @property activeLedgerId 当前 active ledger（拉取前后各验一次，账本切换竞态时丢弃）。
 * @property currentMonth 检测月 `yyyy-MM`。生产传 Asia/Shanghai 当月——对齐服务端统计口径
 *   （`COALESCE(expense_time, confirmed_at)` 按沪月聚合），不用设备时区（跨日几小时窗口里
 *   会拉错相邻月，错配口径宁可保守）。可注入便于测试钉边界。
 * @property monotonicNowMillis 单调毫秒时钟（throttle 用，生产传 `SystemClock.elapsedRealtime`，
 *   不用墙钟避免改时间穿越 throttle）。
 * @property logWarning 轻量日志注入：source 失败时记 error class，**不记** token / 金额明细。
 *   注入而非直接 android.util.Log 是为了纯 JVM 测试不触发未 mock 的 Log 桩。
 */
class BudgetOverspendRuntime(
    val budgetOverspendAlertsEnabled: () -> Boolean,
    val activeLedgerId: () -> String?,
    val currentMonth: () -> String,
    val monotonicNowMillis: () -> Long,
    val logWarning: (String, Throwable?) -> Unit = { _, _ -> },
)

/**
 * 预算超支提醒检测器（轴 6 主动性 · 五类事件之四）。挂在「确认态写入本地缓存」单点
 * （[ExpenseRepositoryCore.cacheIfConfirmed][com.ticketbox.data.repository.ExpenseRepositoryCore] →
 * `onConfirmedCommitted` 回调）：在线确认 / 手动记账 / 详情拉取发现 confirmed 都会触发一次检测。
 *
 * 覆盖边界（KDoc 级契约，有意的 MVP 取舍）：离线确认的 outbox 重放成功（dispatcher 不走
 * cacheIfConfirmed）与他端（/web）确认推高的超支**不会**即时触发——由本端下一次在线确认动作补检。
 * 提醒不是对账：迟到一拍可接受，漏报不可接受的场景（看板）在 /web dashboard 已有 budget_is_over 红字。
 *
 * 频率与去重（三道闸，依次短路）：
 * 1. 月级 sent-key（[BudgetOverspendStore]）：同账本同月已提醒 → 永久跳过（一月一响，防骚扰）。
 * 2. throttle（[CHECK_THROTTLE_MILLIS]，进程内）：未超支时高频确认/详情拉取至多每 10 分钟
 *    真正拉一次预算 API。拉取**前**占坑——source 失败也算一次，避免网络故障时每次确认都重试。
 * 3. 开关 + active ledger 前置门：开关关 / 非当前账本 → 不拉。
 *
 * 失败一律安全降级：source 失败只记轻量日志，绝不影响确认主链路（fire-and-forget，
 * [checkAfterConfirmedWrite] 在注入的 [scope] 上 launch，不阻塞调用方）。
 *
 * 不得：写服务端任何状态、在客户端重算超支口径（只读服务端 [BudgetMonthly.overspentAmountCents]）、
 * 引入周期 worker（这是事件驱动检测，不落 ADR-0046 的 worker 边界）。
 */
class BudgetOverspendChecker(
    private val source: BudgetOverspendSource,
    private val store: BudgetOverspendStore,
    private val dispatcher: BudgetOverspendDispatcher,
    private val runtime: BudgetOverspendRuntime,
    private val scope: CoroutineScope,
) {
    /** key = `ledgerId:month` → 上次真正拉预算的单调毫秒。进程内即可（重启重查一次无害）。 */
    private val lastCheckedAtMillis = ConcurrentHashMap<String, Long>()

    /** 确认链路上的 fire-and-forget 入口：立即返回，检测在 [scope] 上异步跑。 */
    fun checkAfterConfirmedWrite(ledgerId: String) {
        scope.launch { checkNow(ledgerId) }
    }

    /** 一次完整检测（suspend，测试直调）。流程见类 KDoc 的三道闸。 */
    suspend fun checkNow(ledgerId: String) {
        if (ledgerId.isBlank()) return
        if (!runtime.budgetOverspendAlertsEnabled()) return
        if (runtime.activeLedgerId() != ledgerId) return
        val month = runtime.currentMonth()
        if (store.wasSent(budgetOverspendSentKey(ledgerId, month))) return
        if (!claimThrottleSlot(ledgerId, month)) return
        val budget = source.monthlyBudget(month).getOrElse { error ->
            runtime.logWarning("budget overspend check failed: ${error::class.java.simpleName}", error)
            return
        }
        // 响应月与请求月不一致（不该发生）→ 丢弃，保证 sent-key 与查询 key 永不错位。
        if (budget.month != month) return
        // 拉取期间切了账本 → monthlyBudget 绑的是新 active ledger 的数据，丢弃。
        if (runtime.activeLedgerId() != ledgerId) return
        val decision = evaluateBudgetOverspend(ledgerId, budget) ?: return
        if (dispatcher.dispatch(decision) == BudgetOverspendDispatchOutcome.SENT) {
            store.markSent(decision.key)
        }
    }

    /**
     * 原子占坑：距上次拉取不足 [CHECK_THROTTLE_MILLIS] → false（本次跳过）。
     * compute 的原子性保证并发确认只放行一个检测（其余拿到刚写入的时间戳）。
     */
    private fun claimThrottleSlot(ledgerId: String, month: String): Boolean {
        val now = runtime.monotonicNowMillis()
        var claimed = false
        lastCheckedAtMillis.compute("$ledgerId:$month") { _, last ->
            if (last != null && now - last < CHECK_THROTTLE_MILLIS) {
                last
            } else {
                claimed = true
                now
            }
        }
        return claimed
    }

    companion object {
        /** 未超支时两次真实预算拉取的最小间隔。月级事件，10 分钟延迟无感。 */
        const val CHECK_THROTTLE_MILLIS: Long = 10 * 60 * 1000L
    }
}
