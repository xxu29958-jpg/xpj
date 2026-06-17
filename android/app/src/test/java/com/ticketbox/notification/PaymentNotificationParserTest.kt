package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentNotificationDraft
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
        val draft = expenseOf(
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
        val draft = expenseOf(
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
        val draft = expenseOf(
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
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.tencent.mm", title = "微信支付", text = "收款到账 ¥88.00"),
            ),
        )
    }

    @Test
    fun parsesExpenseNotificationWithPayeeLabel() {
        val draft = expenseOf(
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
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.example.news", title = "新闻", text = "今日消费趋势报告 ¥99.00"),
            ),
        )
    }

    @Test
    fun rejectsWechatTextFromUntrustedPackage() {
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.example.spoof", title = "微信支付", text = "你已成功付款给 星巴克 ¥25.80"),
            ),
        )
    }

    @Test
    fun rejectsAlipayTextFromUntrustedPackage() {
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.example.spoof", title = "支付宝", text = "付款成功 ￥12.34 商家：便利蜂"),
            ),
        )
    }

    @Test
    fun rejectsBankContextFromNonSmsPackage() {
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(
                    packageName = "com.example.spoof",
                    title = "招商银行",
                    text = "您尾号1234储蓄账户支出人民币88.00元，交易商户：美团",
                ),
            ),
        )
    }

    // ── §杠杆③ 还款分类器 ──────────────────────────────────────────────

    @Test
    fun parsesAlipayHuabeiRepayment() {
        val draft = repaymentOf(
            snapshot(packageName = "com.eg.android.AlipayGphone", title = "支付宝", text = "花呗还款成功 ¥500.00"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.Alipay, draft.source)
        assertEquals(50_000L, draft.amountCents)
        assertEquals("花呗", draft.merchantLabel)
        assertEquals("2026-05-13T08:00:00Z", draft.capturedAt)
    }

    @Test
    fun parsesJdBaitiaoRepayment() {
        val draft = repaymentOf(
            snapshot(packageName = "com.jingdong.app.mall", title = "京东", text = "白条还款成功，本期 ¥1,200.00"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.Jd, draft.source)
        assertEquals(120_000L, draft.amountCents)
        assertEquals("白条", draft.merchantLabel)
    }

    @Test
    fun parsesJdFinanceRepaymentFromSecondaryPackage() {
        val draft = repaymentOf(
            snapshot(packageName = "com.jd.jrapp", title = "京东金融", text = "您的白条还款¥300已完成"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.Jd, draft.source)
        assertEquals(30_000L, draft.amountCents)
    }

    @Test
    fun parsesMeituanMonthlyRepayment() {
        val draft = repaymentOf(
            snapshot(packageName = "com.sankuai.meituan", title = "美团", text = "美团月付还款成功 ¥88.00"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.Meituan, draft.source)
        assertEquals(8800L, draft.amountCents)
        assertEquals("美团月付", draft.merchantLabel)
    }

    @Test
    fun parsesWechatCreditCardRepayment() {
        val draft = repaymentOf(
            snapshot(packageName = "com.tencent.mm", title = "微信支付", text = "信用卡还款成功 ¥1200.00"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.WeChat, draft.source)
        assertEquals(120_000L, draft.amountCents)
    }

    @Test
    fun creditCardAutoDebitRepaymentIsNotDoubleCountedAsExpense() {
        // 双计 bug 钉死：含「扣款」的信用卡自动还款过去会被当作新支出（扣款 在 expenseWords 里）。还款分类
        // **优先于**消费，故这条落成还款草稿、绝不再落支出。
        val result = PaymentNotificationParser.parse(
            snapshot(
                packageName = "com.android.mms",
                title = "招商银行",
                text = "您尾号1234信用卡自动还款扣款人民币1200.00元，还款成功",
            ),
        )

        assertTrue(result is PaymentNotificationResult.Repayment)
        val draft = (result as PaymentNotificationResult.Repayment).draft
        assertEquals(RepaymentDraftSource.BankSms, draft.source)
        assertEquals(120_000L, draft.amountCents)
        assertEquals("尾号1234", draft.merchantLabel)
        // 反向：绝不同时被当成支出。
        assertNull(expenseOf(result))
    }

    @Test
    fun ignoresRepaymentReminderWithoutActualRepayment() {
        // 「待还款 / 还款日」是提醒(钱还没动),不该落成还款草稿(§8 只捕获已发生的还款)。
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(
                    packageName = "com.eg.android.AlipayGphone",
                    title = "支付宝",
                    text = "您的花呗本期待还款 ¥1,200.00，还款日为6月10日，请按时还款",
                ),
            ),
        )
    }

    @Test
    fun ignoresJdPurchaseExpenseSinceJdIsRepaymentOnlyChannel() {
        // 京东是**还款专用**捕获渠道(杠杆③):它的消费通知不落支出草稿(NotificationDraftSource 无 JD 取值)。
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.jingdong.app.mall", title = "京东", text = "下单成功，付款成功 ¥99.00"),
            ),
        )
    }

    @Test
    fun ignoresRepaymentWithUnparsableAmount() {
        assertNull(
            PaymentNotificationParser.parse(
                snapshot(packageName = "com.eg.android.AlipayGphone", title = "支付宝", text = "花呗还款成功"),
            ),
        )
    }

    @Test
    fun isCandidatePackageGatesAllowlistBeforeReadingText() {
        // 白名单 = 值不值得读这条通知的正文（隐私：非候选包的正文连扫都不扫）。微信/支付宝/京东/京东金融/
        // 美团/短信类是候选。
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.tencent.mm"))
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.eg.android.AlipayGphone")) // 大小写归一
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.android.messaging"))
        // §杠杆③ 新增:京东(白条) / 京东金融 / 美团(月付)还款渠道。
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.jingdong.app.mall"))
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.jd.jrapp"))
        assertTrue(PaymentNotificationParser.isCandidatePackage("com.sankuai.meituan"))
        assertFalse(PaymentNotificationParser.isCandidatePackage("com.example.news"))
        assertFalse(PaymentNotificationParser.isCandidatePackage("com.example.spoof"))
    }

    private fun expenseOf(snapshot: PaymentNotificationSnapshot): NotificationDraft? =
        expenseOf(PaymentNotificationParser.parse(snapshot))

    private fun expenseOf(result: PaymentNotificationResult?): NotificationDraft? =
        (result as? PaymentNotificationResult.Expense)?.draft

    private fun repaymentOf(snapshot: PaymentNotificationSnapshot): RepaymentNotificationDraft? =
        (PaymentNotificationParser.parse(snapshot) as? PaymentNotificationResult.Repayment)?.draft

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
