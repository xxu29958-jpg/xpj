package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DebtInstallmentUiTest {

    @Test
    fun installmentPerPeriodCentsFloorsAndGuardsZero() {
        // §B 每期本金估算 = 本金 ÷ 期数 的整数 floor，镜像后端 `per_period = principal // count`。
        assertEquals(10_000L, installmentPerPeriodCents(principalCents = 120_000L, count = 12L))
        // 分数部分 ≥ 0.5 的用例钉死 floor（非四舍五入）：100 ÷ 8 = 12.5 → floor 12（round 会给 13 → 红），
        // 与后端 `100 // 8 == 12` 一致。这条是 floor-vs-round 的鉴别用例。
        assertEquals(12L, installmentPerPeriodCents(principalCents = 100L, count = 8L))
        // 不整除且分数 < 0.5 → 同样 floor（100 ÷ 12 = 8，余数丢弃）。
        assertEquals(8L, installmentPerPeriodCents(principalCents = 100L, count = 12L))
        // 本金 < 期数 → 每期 0（degenerate，但不崩）。
        assertEquals(0L, installmentPerPeriodCents(principalCents = 5L, count = 12L))
        // 防御除零：count ≤ 0 → 0（实际不会发生——已排期债 count ≥ 1——但守住 / 0 的 500/崩溃。）
        assertEquals(0L, installmentPerPeriodCents(principalCents = 120_000L, count = 0L))
    }

    @Test
    fun shouldShowInstallmentCardOnlyForOpenScheduledInstallment() {
        // 进行中 + 已排期 installment 外部债 → 显示。
        assertTrue(shouldShowInstallmentCard(debt(DebtLinkStatuses.OPEN, DebtKinds.INSTALLMENT, 12)))
        // 红线 R1 兜底：已结清 / 作废债不显示卡片（避免在已早还清的债上显示未来还清日 + N/N 进度的矛盾画面）。
        assertFalse(shouldShowInstallmentCard(debt(DebtLinkStatuses.CLEARED, DebtKinds.INSTALLMENT, 12)))
        assertFalse(shouldShowInstallmentCard(debt(DebtLinkStatuses.VOIDED, DebtKinds.INSTALLMENT, 12)))
        // 非 installment（即便带 count）/ installment 但未排期（count=null）→ 不显示。
        assertFalse(shouldShowInstallmentCard(debt(DebtLinkStatuses.OPEN, DebtKinds.REVOLVING, 12)))
        assertFalse(shouldShowInstallmentCard(debt(DebtLinkStatuses.OPEN, DebtKinds.INSTALLMENT, null)))
    }

    @Test
    fun installmentProgressPairClampsAndStaysNeutral() {
        // 正常进度对（已还, 总）。
        assertEquals(5L to 12L, installmentProgressPair(paidCount = 5L, count = 12L))
        // 红线 R1：paid==count（提额情形）也只返回 (count, count) 这个中性对，不进入任何「完成」分支。
        assertEquals(12L to 12L, installmentProgressPair(paidCount = 12L, count = 12L))
        // null → 0；越界（>count）clamp 到 count（不显示「已还 13/12 期」）。
        assertEquals(0L to 12L, installmentProgressPair(paidCount = null, count = 12L))
        assertEquals(12L to 12L, installmentProgressPair(paidCount = 15L, count = 12L))
    }

    private fun debt(status: String, kind: String, installmentCount: Long?): Debt = Debt(
        publicId = "d",
        ledgerId = "owner",
        direction = DebtDirections.I_OWE,
        counterpartyType = DebtCounterpartyTypes.EXTERNAL,
        counterpartyAccountId = null,
        counterpartyLabel = "分期",
        principalAmountCents = 120_000,
        remainingAmountCents = 0,
        paidAmountCents = 0,
        status = status,
        sourceType = DebtSourceTypes.MANUAL,
        sourceId = null,
        debtKind = kind,
        installmentCount = installmentCount,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = null,
        originalAmountMinor = null,
        createdAt = "2026-06-15T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = 1,
    )
}
