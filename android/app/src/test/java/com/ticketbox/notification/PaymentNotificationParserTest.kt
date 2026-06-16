package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraftSource
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

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
    fun parsesExpenseNotificationWithPayeeLabel() {
        val draft = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.tencent.mm",
                title = "微信支付",
                text = "支付成功 ¥19.90 收款方：瑞幸咖啡",
            ),
        )

        assertNotNull(draft)
        assertEquals(NotificationDraftSource.WeChat, draft.source)
        assertEquals(1990L, draft.amountCents)
        assertEquals("瑞幸咖啡", draft.merchant)
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

    @Test
    fun isCandidatePackageGatesAllowlistBeforeReadingText() {
        // 白名单 = 值不值得读这条通知的正文（隐私：非候选包的正文连扫都不扫）。只微信/支付宝/短信类是候选。
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.tencent.mm"))
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.eg.android.AlipayGphone")) // 大小写归一
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.android.messaging"))
        assertFalse(PaymentNotificationParser.isCandidatePackage("com.example.news"))
        assertFalse(PaymentNotificationParser.isCandidatePackage("com.example.spoof"))
        // 已知盲区：京东白条走 JD 主 App 包，不在白名单——将来要自动追白条须显式加入（产品决策）。
        assertFalse(PaymentNotificationParser.isCandidatePackage("com.jingdong.app.mall"))
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
