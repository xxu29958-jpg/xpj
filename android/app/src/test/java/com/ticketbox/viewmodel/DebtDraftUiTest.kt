package com.ticketbox.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DebtDraftUiTest {

    @Test
    fun parsedAmountCentsConvertsYuanAndRejectsInvalidInput() {
        // yuan → cents (2-decimal home currency), trimming whitespace.
        assertEquals(12_345L, DebtDraftUi(amountYuanInput = "123.45").parsedAmountCents())
        assertEquals(10_000L, DebtDraftUi(amountYuanInput = " 100 ").parsedAmountCents())
        // §3 BigDecimal 精度：>2 位小数按 HALF_UP 精确进位。"1.005" → 101；旧 Double Math.round 给 100
        // （1.005*100 的 double 是 100.4999… → 100），故此断言会在退回 Double 时变红。
        assertEquals(101L, DebtDraftUi(amountYuanInput = "1.005").parsedAmountCents())
        // 溢出 Long 安全返回 null（旧 Double Math.round 会回 Long.MAX 垃圾值而非 null）。
        assertNull(DebtDraftUi(amountYuanInput = "99999999999999999999").parsedAmountCents())
        // Empty / non-numeric / non-positive all reject (parsedAmountCents == null).
        assertNull(DebtDraftUi(amountYuanInput = "").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "abc").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "-5").parsedAmountCents())
        assertNull(DebtDraftUi(amountYuanInput = "0").parsedAmountCents())
    }

    @Test
    fun parsedInstallmentCountAcceptsPositiveIntInRangeRejectsRest() {
        // §B 期数：正整数且 1..600（镜像后端 installment_count gt=0/le=600），前后空白容忍。
        assertEquals(12, DebtDraftUi(installmentCountInput = "12").parsedInstallmentCount())
        assertEquals(1, DebtDraftUi(installmentCountInput = " 1 ").parsedInstallmentCount())
        assertEquals(600, DebtDraftUi(installmentCountInput = "600").parsedInstallmentCount())
        // Empty / non-numeric / non-positive / over the cap / non-integer all reject → null
        // （不排期，也不会用一个会被后端 422 的非法期数去创建）。
        assertNull(DebtDraftUi(installmentCountInput = "").parsedInstallmentCount())
        assertNull(DebtDraftUi(installmentCountInput = "abc").parsedInstallmentCount())
        assertNull(DebtDraftUi(installmentCountInput = "0").parsedInstallmentCount())
        assertNull(DebtDraftUi(installmentCountInput = "-3").parsedInstallmentCount())
        assertNull(DebtDraftUi(installmentCountInput = "601").parsedInstallmentCount())
        assertNull(DebtDraftUi(installmentCountInput = "12.5").parsedInstallmentCount())
    }

    @Test
    fun parsedInstallmentPeriodAcceptsPositiveIntInRangeRejectsRest() {
        // §B 还款周期（每几个月）：正整数且 1..120（镜像后端 installment_period_months le=120）。
        assertEquals(3, DebtDraftUi(installmentPeriodInput = "3").parsedInstallmentPeriod())
        assertEquals(1, DebtDraftUi(installmentPeriodInput = " 1 ").parsedInstallmentPeriod())
        assertEquals(120, DebtDraftUi(installmentPeriodInput = "120").parsedInstallmentPeriod())
        // 空 → null（后端默认每月）；非法 / 非正 / 越界 / 小数 → null。
        assertNull(DebtDraftUi(installmentPeriodInput = "").parsedInstallmentPeriod())
        assertNull(DebtDraftUi(installmentPeriodInput = "0").parsedInstallmentPeriod())
        assertNull(DebtDraftUi(installmentPeriodInput = "121").parsedInstallmentPeriod())
        assertNull(DebtDraftUi(installmentPeriodInput = "3.5").parsedInstallmentPeriod())
    }
}
