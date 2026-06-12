package com.ticketbox.notification.recurring

import kotlinx.coroutines.test.runTest
import java.io.IOException
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0046 Slice 4：[RecurringReminderEngine] 编排契约（Confirmation「Engine tests」照单）。
 * 全部 fake source / fake store / fake dispatcher + 固定 today，证业务契约不引入 Android scheduler 噪音。
 */
class RecurringReminderEngineTest {

    private val today = LocalDate.parse("2026-06-10")

    private fun engine(
        source: RecurringReminderSource,
        store: RecurringReminderStore = InMemoryRecurringReminderStore(),
        dispatcher: FakeRecurringReminderDispatcher = FakeRecurringReminderDispatcher(),
        enabled: Boolean = true,
        sessionReady: Boolean = true,
    ): RecurringReminderEngine = RecurringReminderEngine(
        source = source,
        policy = RecurringReminderPolicy(),
        store = store,
        dispatcher = dispatcher,
        runtime = RecurringReminderRuntime(
            recurringRemindersEnabled = { enabled },
            sessionReady = { sessionReady },
            today = { today },
        ),
    )

    @Test
    fun preferenceOffDoesNotPullSourceAndIsSafeSuccess() = runTest {
        val source = FakeRecurringReminderSource.of(recurringItemFixture(nextExpectedDate = "2026-06-09"))
        val store = InMemoryRecurringReminderStore()
        val outcome = engine(source = source, store = store, enabled = false).checkAndNotify()
        assertEquals(RecurringReminderRunOutcome.EMPTY_SUCCESS, outcome)
        assertEquals(0, source.calls) // 开关关 → 不拉 source。
        assertTrue(store.keys.isEmpty()) // 不 markSent。
    }

    @Test
    fun notLoggedInIsSafeSuccessWithoutPullingSource() = runTest {
        val source = FakeRecurringReminderSource.of(recurringItemFixture(nextExpectedDate = "2026-06-09"))
        val store = InMemoryRecurringReminderStore()
        val outcome = engine(source = source, store = store, sessionReady = false).checkAndNotify()
        assertEquals(RecurringReminderRunOutcome.EMPTY_SUCCESS, outcome)
        assertEquals(0, source.calls)
        assertTrue(store.keys.isEmpty())
    }

    @Test
    fun sourceFailureYieldsTransientFailureAndNoMarkSent() = runTest {
        val source = FakeRecurringReminderSource.failing(IOException("offline"))
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher()
        val outcome = engine(source = source, store = store, dispatcher = dispatcher).checkAndNotify()
        assertTrue(outcome is RecurringReminderRunOutcome.TransientFailure)
        assertTrue(store.keys.isEmpty())
        assertTrue(dispatcher.dispatchedKeys.isEmpty()) // 故障 → 不 dispatch。
    }

    @Test
    fun authShapedRepositoryFailureAlsoMapsToBoundedTransientRetry() = runTest {
        // Contract 8 对抗审钉:仓库 NetworkErrorHandler 把 401/403 折叠成
        // RepositoryException(与网络故障同形),engine 刻意不区分——存活但被撤销的
        // token 走有界退避(TransientFailure→Result.retry),不 mark sent、不 dispatch;
        // token 已清的常见失效态由 sessionReady 前置门拦截(见上方 session 测试)。
        val source = FakeRecurringReminderSource.failing(
            com.ticketbox.data.repository.RepositoryException(
                message = "登录已失效，请重新绑定设备。",
                errorCode = "invalid_token",
            ),
        )
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher()
        val outcome = engine(source = source, store = store, dispatcher = dispatcher).checkAndNotify()
        assertTrue(outcome is RecurringReminderRunOutcome.TransientFailure)
        assertTrue(store.keys.isEmpty())
        assertTrue(dispatcher.dispatchedKeys.isEmpty())
    }

    @Test
    fun policyNoneIsNeitherCheckedNorMarked() = runTest {
        // 全部窗口外（today+30）→ policy NONE：不 dispatch、不写 sent key。
        val source = FakeRecurringReminderSource.of(
            recurringItemFixture(publicId = "a", nextExpectedDate = "2026-07-10"),
        )
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher()
        val outcome = engine(source = source, store = store, dispatcher = dispatcher).checkAndNotify()
        val success = outcome as RecurringReminderRunOutcome.Success
        assertEquals(1, success.scanned)
        assertEquals(0, success.due)
        assertEquals(0, success.sent)
        assertTrue(dispatcher.dispatchedKeys.isEmpty())
        assertTrue(store.keys.isEmpty())
    }

    @Test
    fun alreadySentItemIsNotDispatchedAgain() = runTest {
        val item = recurringItemFixture(publicId = "a", ledgerId = "L", nextExpectedDate = "2026-06-12")
        val key = recurringReminderSentKey("L", "a", LocalDate.parse("2026-06-12"), RecurringReminderKind.DUE_SOON)
        val store = InMemoryRecurringReminderStore(initial = setOf(key))
        val dispatcher = FakeRecurringReminderDispatcher()
        val outcome = engine(
            source = FakeRecurringReminderSource.of(item),
            store = store,
            dispatcher = dispatcher,
        ).checkAndNotify()
        val success = outcome as RecurringReminderRunOutcome.Success
        assertEquals(1, success.due)
        assertEquals(0, success.sent)
        assertEquals(1, success.skippedAlreadySent)
        assertTrue(dispatcher.dispatchedKeys.isEmpty()) // 已提醒 → 不再 dispatch。
    }

    @Test
    fun dispatchSkippedDoesNotMarkSent() = runTest {
        // dispatcher 返回 SKIPPED_*（如权限/开关关）→ 不 markSent，下轮可再尝试。
        val item = recurringItemFixture(publicId = "a", ledgerId = "L", nextExpectedDate = "2026-06-12")
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher {
            RecurringReminderDispatchOutcome.SKIPPED_PERMISSION_DENIED
        }
        val outcome = engine(
            source = FakeRecurringReminderSource.of(item),
            store = store,
            dispatcher = dispatcher,
        ).checkAndNotify()
        val success = outcome as RecurringReminderRunOutcome.Success
        assertEquals(1, success.due)
        assertEquals(0, success.sent)
        assertEquals(1, success.skippedDispatch)
        assertTrue(store.keys.isEmpty()) // 关键：skipped 不写「已提醒」。
        assertEquals(1, dispatcher.dispatchedKeys.size) // 但确实尝试过一次。
    }

    @Test
    fun dispatchSentMarksSent() = runTest {
        val item = recurringItemFixture(publicId = "a", ledgerId = "L", nextExpectedDate = "2026-06-12")
        val key = recurringReminderSentKey("L", "a", LocalDate.parse("2026-06-12"), RecurringReminderKind.DUE_SOON)
        val store = InMemoryRecurringReminderStore()
        val outcome = engine(
            source = FakeRecurringReminderSource.of(item),
            store = store,
        ).checkAndNotify()
        val success = outcome as RecurringReminderRunOutcome.Success
        assertEquals(1, success.sent)
        assertTrue(store.wasSent(key)) // SENT → markSent。
    }

    @Test
    fun multipleItemsProcessedIndependentlyAndBadDateSkipsOnlyThatItem() = runTest {
        // 三条：一条窗口内（发）、一条坏日期（跳过该条不炸）、一条逾期（发）。
        val source = FakeRecurringReminderSource.of(
            recurringItemFixture(publicId = "due", ledgerId = "L", nextExpectedDate = "2026-06-12"),
            recurringItemFixture(publicId = "bad", ledgerId = "L", nextExpectedDate = "not-a-date"),
            recurringItemFixture(publicId = "over", ledgerId = "L", nextExpectedDate = "2026-06-01"),
        )
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher()
        val outcome = engine(source = source, store = store, dispatcher = dispatcher).checkAndNotify()
        val success = outcome as RecurringReminderRunOutcome.Success
        assertEquals(3, success.scanned)
        assertEquals(2, success.due) // 坏日期那条不计 due。
        assertEquals(2, success.sent)
        assertEquals(2, dispatcher.dispatchedKeys.size)
    }

    @Test
    fun dueSoonAndOverdueDedupeSeparatelyAcrossRuns() = runTest {
        // 同一 item 先 DUE_SOON 发过；下次它变 OVERDUE（expectedDate 移到过去）应再发一次——
        // 两个 kind 是不同 key，去重互不抑制。
        val store = InMemoryRecurringReminderStore()
        val dispatcher = FakeRecurringReminderDispatcher()

        // Run 1：窗口内 → DUE_SOON 发出并 markSent。
        engine(
            source = FakeRecurringReminderSource.of(
                recurringItemFixture(publicId = "a", ledgerId = "L", nextExpectedDate = "2026-06-12"),
            ),
            store = store,
            dispatcher = dispatcher,
        ).checkAndNotify()

        // Run 2：同 item 逾期 → OVERDUE 仍发出（不同 key）。
        val outcome2 = engine(
            source = FakeRecurringReminderSource.of(
                recurringItemFixture(publicId = "a", ledgerId = "L", nextExpectedDate = "2026-06-09"),
            ),
            store = store,
            dispatcher = dispatcher,
        ).checkAndNotify()

        val success2 = outcome2 as RecurringReminderRunOutcome.Success
        assertEquals(1, success2.sent)
        val dueSoonKey = recurringReminderSentKey("L", "a", LocalDate.parse("2026-06-12"), RecurringReminderKind.DUE_SOON)
        val overdueKey = recurringReminderSentKey("L", "a", LocalDate.parse("2026-06-09"), RecurringReminderKind.OVERDUE)
        assertTrue(store.wasSent(dueSoonKey))
        assertTrue(store.wasSent(overdueKey))
    }
}
