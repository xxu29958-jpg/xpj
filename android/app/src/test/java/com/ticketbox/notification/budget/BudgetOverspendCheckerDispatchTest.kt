package com.ticketbox.notification.budget

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

/**
 * [BudgetOverspendChecker] 判定与投递契约（轴 6 预算超支通知）：SENT 才 markSent、
 * 未超支不投递、响应月错位 / 账本切换竞态丢弃、fire-and-forget 入口接通。
 * 短路门面在 [BudgetOverspendCheckerTest]（共用 [CheckerHarness]）。
 */
class BudgetOverspendCheckerDispatchTest {

    @Test
    fun overspentBudgetDispatchesAndMarksSentOnlyOnSent() = runTest {
        val harness = CheckerHarness()
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.dispatched.size)
        assertEquals("v1:budget:ledger-1:2026-06", harness.dispatched.single().key)
        assertEquals(5_000L, harness.dispatched.single().overspentCents)
        assertTrue("v1:budget:ledger-1:2026-06" in harness.store.sent)
    }

    @Test
    fun skippedDispatchDoesNotMarkSent() = runTest {
        // 权限/开关在 notifier 侧拒绝时不得写假「已提醒」——否则用户打开开关后整月收不到。
        val harness = CheckerHarness(
            dispatchOutcome = BudgetOverspendDispatchOutcome.SKIPPED_PERMISSION_DENIED,
        )
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.dispatched.size)
        assertTrue(harness.store.sent.isEmpty())
    }

    @Test
    fun notOverspentBudgetDoesNotDispatch() = runTest {
        val harness = CheckerHarness(budgetResult = { Result.success(budgetOf(overspentCents = 0L)) })
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
        assertEquals(0, harness.dispatched.size)
        assertTrue(harness.store.sent.isEmpty())
    }

    @Test
    fun mismatchedResponseMonthIsDiscarded() = runTest {
        // 响应月 ≠ 请求月（不该发生）→ 丢弃，保证 sent-key 与查询 key 永不错位。
        val harness = CheckerHarness(
            budgetResult = { Result.success(budgetOf(month = "2026-05", overspentCents = 5_000L)) },
        )
        harness.checker.checkNow("ledger-1")
        assertEquals(0, harness.dispatched.size)
        assertTrue(harness.store.sent.isEmpty())
    }

    @Test
    fun ledgerSwitchDuringFetchDiscardsResult() = runTest {
        // 拉取期间切账本：monthlyBudget 绑的是新 active ledger 的数据，结果必须丢弃。
        val harness = CheckerHarness()
        harness.budgetResult = {
            harness.activeLedgerId = "ledger-2"
            Result.success(budgetOf(overspentCents = 5_000L))
        }
        harness.checker.checkNow("ledger-1")
        assertEquals(1, harness.sourceCalls)
        assertEquals(0, harness.dispatched.size)
        assertTrue(harness.store.sent.isEmpty())
    }

    @Test
    fun fireAndForgetEntryRunsCheckOnInjectedScope() = runTest {
        // checkAfterConfirmedWrite 在注入 scope 上 launch；Unconfined 下同步跑完即可断言。
        val harness = CheckerHarness()
        harness.checker.checkAfterConfirmedWrite("ledger-1")
        assertEquals(1, harness.dispatched.size)
    }
}
