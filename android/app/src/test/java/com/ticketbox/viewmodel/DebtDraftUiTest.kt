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
}
