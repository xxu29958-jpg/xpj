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

        val exactTrailingZero = expenseOf(
            snapshot(
                packageName = "com.tencent.mm",
                title = "微信支付",
                text = "你已成功付款给 星巴克 ¥1.230",
            ),
        )
        assertEquals(123L, exactTrailingZero?.amountCents)
        assertTrue(PaymentNotificationParser.parse(snapshot("com.tencent.mm", "微信支付",
            "你已成功付款给 星巴克 ¥10.004")) is PaymentNotificationResult.Review)
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
        for (text in listOf(
            "你有一笔37.90元的支出，领1元生活缴费红包。使用花呗支付，确认收货的订单请及时还款。",
            "账单已出,花呗消费37.90元",
            "37.90元付款成功，462.10元余额",
            "37.90元付款成功，优惠已使用",
            "花呗消费37.90元，领红包立减5元",
            "花呗消费37.90元，还款日为下月10日，请按时还款",
            "领红包5元，花呗付款成功37.90元，还款日为下月10日",
            "账户余额￥500.00，花呗消费37.90元，余额￥462.10",
            "付款成功，订单金额￥42.90，优惠￥5.00，实付37.90元",
        )) {
            val result = expenseOf(snapshot("com.eg.android.AlipayGphone", "支付宝", text))
            assertEquals(3790L, result?.amountCents, text)
            val moved = snapshot("com.eg.android.AlipayGphone", "交易提醒", text)
                .copy(text = null, bigText = text.replace("37.90", "83.25"))
            assertEquals(8325L, expenseOf(moved)?.amountCents, text)
        }
    }

    @Test
    fun parsesBankSmsExpenseNotification() {
        // The same transaction must reach the draft through both built-in and other SMS apps.
        for (pkg in listOf(
            "com.android.mms", "com.android.messaging", "com.google.android.apps.messaging",
            "com.samsung.android.messaging", "org.example.sms.client", "org.example.mms.client",
            "org.example.messagingclient", "org.example.SMS.client",
        )) {
            assertTrue(PaymentNotificationParser.isCandidatePackage(pkg), pkg)
            val draft = expenseOf(snapshot(
                packageName = pkg,
                title = "招商银行",
                text = "您尾号1234储蓄账户支出人民币88.00元，交易商户：美团",
            ))
            assertNotNull(draft, pkg)
            assertEquals(NotificationDraftSource.BankSms, draft.source, pkg)
            assertEquals(8800L, draft.amountCents, pkg)
            assertEquals("美团", draft.merchant, pkg)
        }
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
        // A candidate SMS app alone is not evidence of a bank transaction.
        for (notification in listOf(
            snapshot("org.example.sms.client", "朋友", "付款成功 ￥12.34 商家：便利蜂"),
            snapshot("org.example.mms.client", "招商银行", "本期账单人民币88.00元，还款日为10日"),
        )) {
            assertNull(PaymentNotificationParser.parse(notification), notification.packageName)
        }
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

        // result is Repayment(sealed 互斥子类型)即证明它没被当成支出——这是真正咬住分类顺序的断言:
        // 把 classifyKind 的 repaymentDoneWords 步删掉,「自动还款」会落到 expenseWords→EXPENSE,本断言变红。
        assertTrue(result is PaymentNotificationResult.Repayment)
        val draft = (result as PaymentNotificationResult.Repayment).draft
        assertEquals(RepaymentDraftSource.BankSms, draft.source)
        assertEquals(120_000L, draft.amountCents)
        assertEquals("尾号1234", draft.merchantLabel)
    }

    @Test
    fun parsesRepaymentCreditedDespiteIncomeWord() {
        // 防回归(对抗审 P2)：含「到账」的真实还款不被收入词先吞掉(还款判定优先于 incomeWords)。
        val draft = repaymentOf(
            snapshot(packageName = "com.eg.android.AlipayGphone", title = "支付宝", text = "您的花呗还款¥500.00已到账"),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.Alipay, draft.source)
        assertEquals(50_000L, draft.amountCents)
    }

    @Test
    fun parsesExpenseWithBillReminderTail() {
        // 防回归(对抗审 P2)：消费通知附带「本期应还」账单提醒尾巴时仍按支出捕获,不被提醒步骤吞掉。
        val draft = expenseOf(
            snapshot(
                packageName = "com.android.mms",
                title = "招商银行",
                text = "您尾号1234信用卡消费人民币88.00元，交易商户：美团，本期应还¥1288",
            ),
        )

        assertNotNull(draft)
        assertEquals(NotificationDraftSource.BankSms, draft.source)
        assertEquals(8800L, draft.amountCents)
    }

    @Test
    fun parsesRepaymentAmountAfterBillTotalNotFirstAmount() {
        // 对抗审 P3：银行账单「本期账单¥1288已还款¥500」首金额是账单总额,还款额取还款词之后的 500。
        val draft = repaymentOf(
            snapshot(
                packageName = "com.android.mms",
                title = "招商银行",
                text = "您尾号1234信用卡本期账单¥1,288.00，已还款¥500.00成功",
            ),
        )

        assertNotNull(draft)
        assertEquals(RepaymentDraftSource.BankSms, draft.source)
        assertEquals(50_000L, draft.amountCents)
        val mixedUnits = repaymentOf(snapshot(
            "com.android.mms", "招商银行", "本期账单￥1288，已还款500元，余额￥788",
        ))
        assertEquals(50_000L, mixedUnits?.amountCents)
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
        for (text in listOf(
            "领取红包5元，还款日为10日",
        )) {
            assertNull(PaymentNotificationParser.parse(snapshot("com.eg.android.AlipayGphone", "支付宝", text)), text)
        }
    }

    @Test
    fun capturesJdAndMeituanPurchasesWithoutInventingRepayments() {
        for (pkg in listOf("com.jingdong.app.mall", "com.sankuai.meituan")) {
            assertEquals(9900L, expenseOf(snapshot(pkg, "交易提醒", "下单成功，付款成功 ¥99.00"))?.amountCents)
        }
    }

    @Test
    fun keepsUncertainTransactionsForReview() {
        for (text in listOf("花呗还款成功", "花呗还款成功￥37.90，款项已退款",
            "花呗还款成功￥37.90，因账户异常退回", "消费37.90元，消费80元")) {
            val result = PaymentNotificationParser.parse(snapshot("com.eg.android.AlipayGphone", "交易提醒", text))
            assertTrue(result is PaymentNotificationResult.Review, text)
            assertTrue(result.candidates.isNotEmpty())
        }
        for (text in listOf("还入500元", "已还清500元", "还款成功500元，本期应还0元（尾号1234）")) {
            val result = repaymentOf(snapshot("com.eg.android.AlipayGphone", "交易提醒", text))
            assertEquals(50000L, result?.amountCents, text)
            if (text.contains("尾号")) assertEquals("尾号1234", result?.merchantLabel)
        }
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
