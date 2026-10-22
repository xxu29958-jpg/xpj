package com.ticketbox.notification

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationTimeEvidenceTest {
    @Test fun delayedDeliveryKeepsTransactionAndDeliveryLiteralsWithoutAccountOrBody() {
        val result = assertIs<PaymentNotificationResult.Expense>(PaymentNotificationParser.parse(
            PaymentNotificationSnapshot("com.tencent.mm", "微信支付", "付款成功￥25.00，交易时间：12月31日23:59，" +
                "接收时间：2026-01-01 10:00，账户尾号1234。私密备注不要发送", null, null,
                Instant.parse("2026-01-01T02:00:01Z").toEpochMilli())))
        assertNull(result.draft.expenseTime)
        assertEquals("2026-01-01T02:00:01Z", result.capturedAt)
        val evidence = requireNotNull(result.timeEvidence)
        assertEquals(listOf("12月31日23:59", "2026-01-01 10:00"), evidence.fragments.map { it.literal })
        assertEquals(listOf("交易时间", "接收时间"), evidence.fragments.map { it.label })
        assertFalse(evidence.toString().contains("1234"))
        assertFalse(evidence.toString().contains("私密备注"))
    }

    @Test fun literalExtractionKeepsAmbiguityAndMarksOverflowInsteadOfChoosingFirstTime() {
        val text = "09:41\n下单时间：2026-01-02 10:00\n支付时间：02/03/2026 11:22+0800\n" +
            "还款时间：2026-03-02 12:00 CST\n交易时间：昨天 23:59\n交易时间：12:30"
        val evidence = NotificationTimeExtractor.read(listOf("text" to text), "America/New_York")
        assertEquals("America/New_York", evidence.sourceTimezone)
        assertEquals(listOf("2026-01-02 10:00", "02/03/2026 11:22+0800", "2026-03-02 12:00 CST", "昨天 23:59", "12:30"),
            evidence.fragments.map { it.literal })
        assertFalse(evidence.truncated)
        val many = NotificationTimeExtractor.read(listOf("text" to (1..10).joinToString("\n") { "交易时间：2026-01-$it 12:30" }))
        assertEquals(8, many.fragments.size)
        assertTrue(many.truncated)
    }
}
