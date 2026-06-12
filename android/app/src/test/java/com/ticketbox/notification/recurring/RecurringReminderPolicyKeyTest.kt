package com.ticketbox.notification.recurring

import com.ticketbox.domain.model.RecurringItem
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * ADR-0046 Slice 2：[RecurringReminderPolicy] 的日期缺失/不可解析、frequency 无关、sent-key 稳定性
 * （Confirmation「Policy tests」照单·下半）。从 [RecurringReminderPolicyTest] 拆出以守 detekt
 * TooManyFunctions（每类 ≤11 函数）。today 固定 2026-06-10。
 */
class RecurringReminderPolicyKeyTest {

    private val policy = RecurringReminderPolicy()
    private val today = LocalDate.parse("2026-06-10")

    private fun item(
        status: String = "active",
        nextExpectedDate: String? = "2026-06-12",
        publicId: String = "rec-1",
        ledgerId: String = "ledger-a",
        merchant: String = "房租",
    ): RecurringItem = recurringItemFixture(
        publicId = publicId,
        ledgerId = ledgerId,
        merchant = merchant,
        status = status,
        nextExpectedDate = nextExpectedDate,
    )

    @Test
    fun nullNextExpectedDateYieldsNone() {
        assertNull(policy.evaluate(today, item(nextExpectedDate = null)))
    }

    @Test
    fun blankNextExpectedDateYieldsNone() {
        assertNull(policy.evaluate(today, item(nextExpectedDate = "   ")))
    }

    @Test
    fun unparsableNextExpectedDateYieldsNone() {
        // 非法格式 item-level skip（不抛、不炸全局）。
        assertNull(policy.evaluate(today, item(nextExpectedDate = "not-a-date")))
    }

    @Test
    fun policyDoesNotBranchOnMonthlyFrequency() {
        // frequency 非 monthly（甚至空）也不影响判定——policy 绝不读 frequency（Contract 3）。
        val weekly = item(nextExpectedDate = "2026-06-12").copy(frequency = "weekly")
        val blank = item(nextExpectedDate = "2026-06-12").copy(frequency = "")
        assertEquals(RecurringReminderKind.DUE_SOON, policy.evaluate(today, weekly)?.kind)
        assertEquals(RecurringReminderKind.DUE_SOON, policy.evaluate(today, blank)?.kind)
    }

    @Test
    fun decisionCarriesStableSentKeyAndContext() {
        // key = v1:{ledgerId}:{itemPublicId}:{expectedDate}:{kind}，且与 builder 同源。
        val decision = policy.evaluate(
            today,
            item(nextExpectedDate = "2026-06-12", publicId = "rec-9", ledgerId = "led-x", merchant = "Netflix"),
        )
        assertEquals("v1:led-x:rec-9:2026-06-12:DUE_SOON", decision?.key)
        assertEquals("led-x", decision?.ledgerId)
        assertEquals("rec-9", decision?.itemPublicId)
        assertEquals("Netflix", decision?.merchant)
        assertEquals(LocalDate.parse("2026-06-12"), decision?.expectedDate)
    }

    @Test
    fun sentKeyBuilderDistinguishesKindAndDate() {
        // 同 ledger/item 不同 kind / 不同 expectedDate 产出不同 key（去重粒度的根）。
        val dueSoon = recurringReminderSentKey("L", "I", LocalDate.parse("2026-06-12"), RecurringReminderKind.DUE_SOON)
        val overdue = recurringReminderSentKey("L", "I", LocalDate.parse("2026-06-12"), RecurringReminderKind.OVERDUE)
        val nextCycle = recurringReminderSentKey("L", "I", LocalDate.parse("2026-07-12"), RecurringReminderKind.DUE_SOON)
        assertEquals("v1:L:I:2026-06-12:DUE_SOON", dueSoon)
        assertEquals("v1:L:I:2026-06-12:OVERDUE", overdue)
        assertEquals("v1:L:I:2026-07-12:DUE_SOON", nextCycle)
    }
}
