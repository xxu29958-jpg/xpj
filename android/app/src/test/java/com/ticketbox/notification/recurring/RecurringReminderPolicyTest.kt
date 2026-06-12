package com.ticketbox.notification.recurring

import com.ticketbox.domain.model.RecurringItem
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * ADR-0046 Slice 2：[RecurringReminderPolicy] 状态 / 日期 / 窗口判定（Confirmation「Policy tests」照单·上半）。
 * 零 Android 依赖——顶层类型直测。today 固定为 2026-06-10 钉边界。
 * 日期缺失 / 不可解析 / frequency 无关 / key 稳定性这几条在 [RecurringReminderPolicyKeyTest]
 * （按 detekt TooManyFunctions 拆出，每类 ≤11 函数）。
 */
class RecurringReminderPolicyTest {

    private val policy = RecurringReminderPolicy()
    private val today = LocalDate.parse("2026-06-10")

    private fun item(
        status: String = "active",
        nextExpectedDate: String? = "2026-06-12",
        publicId: String = "rec-1",
        ledgerId: String = "ledger-a",
        merchant: String = "房租",
    ): RecurringItem = RecurringItem(
        publicId = publicId,
        ledgerId = ledgerId,
        merchant = merchant,
        merchantKey = merchant.lowercase(),
        frequency = "monthly",
        baselineAmountCents = 9900,
        lastAmountCents = 9900,
        occurrenceCount = 3,
        lastSeenAt = "2026-05-01T00:00:00Z",
        nextExpectedDate = nextExpectedDate,
        status = status,
        confidence = "high",
        source = "candidate",
        anomalyStatus = "normal",
        currentMonthAmountCents = null,
        historicalAverageAmountCents = null,
        amountDeltaPercent = null,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        pausedAt = null,
        archivedAt = null,
    )

    @Test
    fun activeWithinWindowYieldsDueSoon() {
        // today <= nextExpectedDate <= today+7 → DUE_SOON。
        val decision = policy.evaluate(today, item(nextExpectedDate = "2026-06-12"))
        assertEquals(RecurringReminderKind.DUE_SOON, decision?.kind)
    }

    @Test
    fun activeOnTodayYieldsDueSoon() {
        // nextExpectedDate == today（窗口含今天）→ DUE_SOON，不算逾期。
        val decision = policy.evaluate(today, item(nextExpectedDate = "2026-06-10"))
        assertEquals(RecurringReminderKind.DUE_SOON, decision?.kind)
    }

    @Test
    fun activeAtWindowEdgeSevenDaysYieldsDueSoon() {
        // 恰好 today+7（含端点）→ DUE_SOON。
        val decision = policy.evaluate(today, item(nextExpectedDate = "2026-06-17"))
        assertEquals(RecurringReminderKind.DUE_SOON, decision?.kind)
    }

    @Test
    fun activeJustPastWindowYieldsNone() {
        // today+8（窗口外的未来）→ NONE。
        assertNull(policy.evaluate(today, item(nextExpectedDate = "2026-06-18")))
    }

    @Test
    fun activeBeforeTodayYieldsOverdue() {
        // nextExpectedDate < today → OVERDUE。
        val decision = policy.evaluate(today, item(nextExpectedDate = "2026-06-09"))
        assertEquals(RecurringReminderKind.OVERDUE, decision?.kind)
    }

    @Test
    fun overdueTakesPriorityOverDueSoon() {
        // 逾期（<today）即便也在「today-7..today」附近也判 OVERDUE，不退化成 DUE_SOON。
        // 钉「OVERDUE 优先」：昨天到期 → OVERDUE。
        val decision = policy.evaluate(today, item(nextExpectedDate = "2026-06-09"))
        assertEquals(RecurringReminderKind.OVERDUE, decision?.kind)
    }

    @Test
    fun pausedYieldsNone() {
        assertNull(policy.evaluate(today, item(status = "paused", nextExpectedDate = "2026-06-12")))
    }

    @Test
    fun archivedYieldsNone() {
        assertNull(policy.evaluate(today, item(status = "archived", nextExpectedDate = "2026-06-12")))
    }

    @Test
    fun unknownStatusYieldsNone() {
        assertNull(policy.evaluate(today, item(status = "candidate", nextExpectedDate = "2026-06-12")))
    }
}
