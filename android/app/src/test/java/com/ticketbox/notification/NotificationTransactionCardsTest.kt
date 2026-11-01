package com.ticketbox.notification

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NotificationTransactionCardsTest {
    private fun snapshot(text: String? = null, lines: List<String> = emptyList()) = PaymentNotificationSnapshot(
        "com.eg.android.alipaygphone", "支付宝", text, null, null, 1_793_524_622_000, lines)

    @Test fun everyInboxCardIsIndependentIncludingEqualAmounts() {
        val results = PaymentNotificationParser.parseAll(snapshot(lines = listOf(
            "你有一笔10.00元的支出，领取2个积分。", "你有一笔12.90元的支出，领1元话费券。",
            "你有一笔29.33元的支出。", "你有一笔10.00元的支出。")))
        assertEquals(listOf(1000L, 1290L, 2933L, 1000L), results.map { (it as PaymentNotificationResult.Expense).draft.amountCents })
        assertTrue(results.all { it.fieldEvidence?.fragments?.isNotEmpty() == true })
    }

    @Test fun repeatedHeadingsKeepAllCardsButOnePaymentAndItsBalanceStayOne() {
        val results = PaymentNotificationParser.parseAll(snapshot(text =
            "交易提醒\n你有一笔10.00元的支出。\n交易提醒\n你有一笔12.90元的支出。"))
        assertEquals(listOf(1000L, 1290L), results.map { (it as PaymentNotificationResult.Expense).draft.amountCents })
        val single = PaymentNotificationParser.parseAll(snapshot(text = "支付成功10元。余额100元。"))
        assertEquals(1, single.size)
        assertEquals(1000L, (single.single() as PaymentNotificationResult.Expense).draft.amountCents)
    }

    @Test fun moreThanTwentyFourEventsAreRetainedAndNonCandidatePackageIsNotParsed() {
        val snapshot = snapshot(lines = (1..30).map { "你有一笔${it}.00元的支出。" })
        assertEquals(30, PaymentNotificationParser.parseAll(snapshot).size)
        assertTrue(PaymentNotificationParser.parseAll(snapshot.copy(packageName = "private.notes")).isEmpty())
    }
}
