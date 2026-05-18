package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraftSource
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class PaymentNotificationParserTest {
    @Test
    fun parsesWechatPaymentNotification() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.tencent.mm",
                title = "微信支付",
                text = "你已成功付款给 星巴克 ¥25.80",
            ),
        )

        assertNotNull(draft)
        assertEquals(NotificationDraftSource.WeChat, draft.source)
        assertEquals(2580L, draft.amountCents)
        assertEquals("星巴克", draft.merchant)
        assertEquals("2026-05-13T08:00:00Z", draft.expenseTime)
    }

    @Test
    fun parsesAlipayPaymentNotification() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.eg.android.AlipayGphone",
                title = "支付宝",
                text = "付款成功 ￥12.34 商家：便利蜂",
            ),
        )

        assertNotNull(draft)
        assertEquals(NotificationDraftSource.Alipay, draft.source)
        assertEquals(1234L, draft.amountCents)
        assertEquals("便利蜂", draft.merchant)
    }

    @Test
    fun parsesBankSmsExpenseNotification() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.android.mms",
                title = "招商银行",
                text = "您尾号1234储蓄账户支出人民币88.00元，交易商户：美团",
            ),
        )

        assertNotNull(draft)
        assertEquals(NotificationDraftSource.BankSms, draft.source)
        assertEquals(8800L, draft.amountCents)
        assertEquals("美团", draft.merchant)
    }

    @Test
    fun rejectsIncomeNotification() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.tencent.mm",
                title = "微信支付",
                text = "收款到账 ¥88.00",
            ),
        )

        assertNull(draft)
    }

    @Test
    fun rejectsGenericNotificationWithoutPaymentContext() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.example.news",
                title = "新闻",
                text = "今日消费趋势报告 ¥99.00",
            ),
        )

        assertNull(draft)
    }

    @Test
    fun rejectsWechatTextFromUntrustedPackage() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.example.spoof",
                title = "微信支付",
                text = "你已成功付款给 星巴克 ¥25.80",
            ),
        )

        assertNull(draft)
    }

    @Test
    fun rejectsAlipayTextFromUntrustedPackage() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.example.spoof",
                title = "支付宝",
                text = "付款成功 ￥12.34 商家：便利蜂",
            ),
        )

        assertNull(draft)
    }

    @Test
    fun rejectsBankContextFromNonSmsPackage() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.example.spoof",
                title = "招商银行",
                text = "您尾号1234储蓄账户支出人民币88.00元，交易商户：美团",
            ),
        )

        assertNull(draft)
    }

    private fun snapshot(
        packageName: String,
        title: String,
        text: String,
    ): PaymentNotificationSnapshot =
        PaymentNotificationSnapshot(
            packageName = packageName,
            title = title,
            text = text,
            bigText = null,
            subText = null,
            postTimeMillis = Instant.parse("2026-05-13T08:00:00Z").toEpochMilli(),
        )
}
