package com.ticketbox.notification.budget

import com.ticketbox.domain.model.BudgetMonthly
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers

/**
 * [BudgetOverspendChecker] 测试共用 doubles（镜像 RecurringReminderTestDoubles 形态）：
 * Gate / Dispatch 两个测试类共享同一套 fake 注入（detekt TooManyFunctions 11/类，
 * 12 个编排契约按「短路门 / 判定投递」拆两类）。
 */
internal class CheckerHarness(
    var budgetResult: () -> Result<BudgetMonthly> = { Result.success(budgetOf(overspentCents = 5_000L)) },
    var dispatchOutcome: BudgetOverspendDispatchOutcome = BudgetOverspendDispatchOutcome.SENT,
) {
    var enabled = true
    var activeLedgerId: String? = "ledger-1"
    var month = "2026-06"
    var nowMillis = 0L
    var sourceCalls = 0
    val dispatched = mutableListOf<BudgetOverspendDecision>()
    val store = RecordingStore()

    val checker = BudgetOverspendChecker(
        source = {
            sourceCalls++
            budgetResult()
        },
        store = store,
        dispatcher = { decision ->
            dispatched += decision
            dispatchOutcome
        },
        runtime = BudgetOverspendRuntime(
            budgetOverspendAlertsEnabled = { enabled },
            activeLedgerId = { activeLedgerId },
            currentMonth = { month },
            monotonicNowMillis = { nowMillis },
        ),
        scope = CoroutineScope(Dispatchers.Unconfined),
    )
}

internal class RecordingStore : BudgetOverspendStore {
    val sent = mutableSetOf<String>()

    override fun wasSent(key: String): Boolean = key in sent

    override fun markSent(key: String) {
        sent += key
    }
}
