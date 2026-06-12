package com.ticketbox.notification.budget

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

/**
 * [BudgetOverspendChecker] 短路门契约（轴 6 预算超支通知）：开关 / active ledger /
 * sent-key / throttle 依次短路，source 失败安全降级。判定与投递面在
 * [BudgetOverspendCheckerDispatchTest]（detekt TooManyFunctions 11/类，按语义拆两类，
 * 共用 [CheckerHarness]）。
 */
class BudgetOverspendCheckerTest {

    @Test
    fun blankLedgerIdShortCircuitsBeforeSource() = runTest {
        val harness = CheckerHarness()
        harness.checker.checkNow("")
        assertEquals(0, harness.sourceCalls)
    }

    @Test
    fun disabledToggleShortCircuitsBeforeSource() = runTest {
        val harness = CheckerHarness()
        harness.enabled = false
        harness.checker.checkNow("ledger-1")
        assertEquals(0, harness.sourceCalls)
    }

    @Test
    fun nonActiveLedgerShortCircuitsBeforeSource() = runTest {
        val harness = CheckerHarness()
        harness.activeLedgerId = "ledger-2"
        harness.checker.checkNow("ledger-1")
        assertEquals(0, harness.sourceCalls)
    }

    @Test
    fun alreadySentMonthShortCircuitsBeforeSource() = runTest {
        val harness = CheckerHarness()
        harness.store.sent += "v1:budget:ledger-1:2026-06"
        harness.checker.checkNow("ledger-1")
        assertEquals(0, harness.sourceCalls)
        assertEquals(0, harness.dispatched.size)
    }

    @Test
    fun throttleSuppressesSecondFetchWithinWindowAndReopensAfter() = runTest {
        // 未超支 → 不 markSent，但 throttle 占坑：10 分钟内的后续确认不再拉预算。
        val harness = CheckerHarness(budgetResult = { Result.success(budgetOf(overspentCents = 0L)) })
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
        harness.nowMillis += BudgetOverspendChecker.CHECK_THROTTLE_MILLIS - 1
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
        harness.nowMillis += 1
        harness.checker.checkNow("ledger-1")
        assertEquals(2, harness.sourceCalls)
    }

    @Test
    fun sourceFailureIsSwallowedAndCountsTowardThrottle() = runTest {
        // source 失败安全降级（不抛、不 dispatch、不 markSent）；失败也占 throttle 坑，
        // 避免网络故障时每次确认都重试拉预算。
        val harness = CheckerHarness(budgetResult = { Result.failure(RuntimeException("boom")) })
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
        assertEquals(0, harness.dispatched.size)
        assertTrue(harness.store.sent.isEmpty())
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
    }
}
