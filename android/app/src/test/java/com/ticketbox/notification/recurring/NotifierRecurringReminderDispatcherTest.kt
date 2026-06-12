package com.ticketbox.notification.recurring

import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0046 Slice 1：[NotifierRecurringReminderDispatcher] 的「结构性空值短路 + 委托透传」纯 JVM 测试。
 *
 * 经窄函数接缝注入 fake `onRecurringDue`（不构造需要 Context 的真 notifier，本模块无 Robolectric）。
 * notifier 自身的开关 / 权限门（SENT / SKIPPED_DISABLED / SKIPPED_PERMISSION_DENIED 的产生）是
 * Android 绑定逻辑，由实机/模拟器覆盖；本测试钉 wrapper 把 notifier 返回的 outcome 原样透传，
 * 且对结构性空值（ledgerId / itemPublicId 空白）短路成 SKIPPED_INVALID_INPUT、不触达 notifier。
 */
class NotifierRecurringReminderDispatcherTest {

    private fun decision(
        ledgerId: String = "ledger-a",
        itemPublicId: String = "rec-1",
        merchant: String = "房租",
    ) = RecurringReminderDecision(
        key = recurringReminderSentKey(ledgerId, itemPublicId, LocalDate.parse("2026-06-12"), RecurringReminderKind.DUE_SOON),
        kind = RecurringReminderKind.DUE_SOON,
        ledgerId = ledgerId,
        itemPublicId = itemPublicId,
        merchant = merchant,
        expectedDate = LocalDate.parse("2026-06-12"),
    )

    @Test
    fun delegatesMerchantAndKeyToNotifierAndReturnsItsOutcome() {
        var seenMerchant: String? = null
        var seenTag: String? = null
        val dispatcher = NotifierRecurringReminderDispatcher { merchant, tag ->
            seenMerchant = merchant
            seenTag = tag
            RecurringReminderDispatchOutcome.SENT
        }
        val d = decision(merchant = "Netflix")
        val outcome = dispatcher.dispatch(d)
        assertEquals(RecurringReminderDispatchOutcome.SENT, outcome)
        assertEquals("Netflix", seenMerchant)
        // dedupeTag 必须是 decision.key（同一去重键贯穿 dispatch → notify tag）。
        assertEquals(d.key, seenTag)
    }

    @Test
    fun passesThroughSkippedDisabled() {
        val dispatcher = NotifierRecurringReminderDispatcher { _, _ ->
            RecurringReminderDispatchOutcome.SKIPPED_DISABLED
        }
        assertEquals(RecurringReminderDispatchOutcome.SKIPPED_DISABLED, dispatcher.dispatch(decision()))
    }

    @Test
    fun passesThroughSkippedPermissionDenied() {
        val dispatcher = NotifierRecurringReminderDispatcher { _, _ ->
            RecurringReminderDispatchOutcome.SKIPPED_PERMISSION_DENIED
        }
        assertEquals(
            RecurringReminderDispatchOutcome.SKIPPED_PERMISSION_DENIED,
            dispatcher.dispatch(decision()),
        )
    }

    @Test
    fun blankLedgerShortCircuitsToInvalidInputWithoutTouchingNotifier() {
        var called = false
        val dispatcher = NotifierRecurringReminderDispatcher { _, _ ->
            called = true
            RecurringReminderDispatchOutcome.SENT
        }
        val outcome = dispatcher.dispatch(decision(ledgerId = "   "))
        assertEquals(RecurringReminderDispatchOutcome.SKIPPED_INVALID_INPUT, outcome)
        assertTrue(!called) // 不触达 notifier。
    }

    @Test
    fun blankItemPublicIdShortCircuitsToInvalidInput() {
        var called = false
        val dispatcher = NotifierRecurringReminderDispatcher { _, _ ->
            called = true
            RecurringReminderDispatchOutcome.SENT
        }
        val outcome = dispatcher.dispatch(decision(itemPublicId = ""))
        assertEquals(RecurringReminderDispatchOutcome.SKIPPED_INVALID_INPUT, outcome)
        assertTrue(!called)
    }

    @Test
    fun blankMerchantStillDelegatesToNotifierForFallback() {
        // 商家为空不是 invalid input：交给 notifier 出「未填写商家」fallback 文案（与草稿口径一致）。
        var seenMerchant: String? = null
        val dispatcher = NotifierRecurringReminderDispatcher { merchant, _ ->
            seenMerchant = merchant
            RecurringReminderDispatchOutcome.SENT
        }
        val outcome = dispatcher.dispatch(decision(merchant = ""))
        assertEquals(RecurringReminderDispatchOutcome.SENT, outcome)
        // 空商家原样透传给 notifier（由 notifier 决定 fallback），wrapper 不在此短路。
        assertEquals("", seenMerchant)
    }
}
