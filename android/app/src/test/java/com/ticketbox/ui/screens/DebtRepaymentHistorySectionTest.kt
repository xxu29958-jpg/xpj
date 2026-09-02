package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepayment
import com.ticketbox.domain.model.DebtRepaymentStatuses
import com.ticketbox.domain.model.DebtRepaymentVoid
import com.ticketbox.domain.model.DebtSourceTypes
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * 单笔还款作废入口的展示资格（纯呈现规则，镜像服务端 guard_direct_fact_writable）：
 * 仅 external+manual 欠款、可写角色、整笔未作废（terminal）、该笔还款仍 active 时才出现。
 * member/bill_split 的历史永远只读；整笔已作废后服务端对后续 fact 一律 debt_already_voided。
 */
class DebtRepaymentHistorySectionTest {

    private fun debt(
        counterpartyType: String = DebtCounterpartyTypes.EXTERNAL,
        status: String = DebtLinkStatuses.OPEN,
        sourceType: String = DebtSourceTypes.MANUAL,
    ): Debt = Debt(
        publicId = "debt-1",
        ledgerId = "owner",
        direction = DebtDirections.I_OWE,
        counterpartyType = counterpartyType,
        counterpartyAccountId = null,
        counterpartyLabel = "对手方",
        principalAmountCents = 10_000,
        remainingAmountCents = 4_000,
        paidAmountCents = 6_000,
        status = status,
        sourceType = sourceType,
        sourceId = null,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = null,
        originalAmountMinor = null,
        createdAt = "2026-06-18T00:00:00Z",
        updatedAt = "2026-06-18T00:00:00Z",
        rowVersion = 1,
    )

    private fun repayment(
        status: String = DebtRepaymentStatuses.ACTIVE,
    ): DebtRepayment = DebtRepayment(
        publicId = "rep-1",
        amountCents = 6_000,
        paidAt = "2026-06-18",
        createdAt = "2026-06-18T00:00:00Z",
        status = status,
        voidFact = if (status == DebtRepaymentStatuses.VOIDED) {
            DebtRepaymentVoid(publicId = "void-1", reason = "记错了", createdAt = "2026-06-19T00:00:00Z")
        } else {
            null
        },
    )

    @Test
    fun `void entry only for direct writable open or cleared debt with active repayment`() {
        assertTrue(repaymentVoidActionAllowed(debt(), canModify = true, repayment = repayment()))
        // 已两清(cleared)仍可作废一笔还款，服务端会重开父欠款。
        assertTrue(
            repaymentVoidActionAllowed(
                debt(status = DebtLinkStatuses.CLEARED),
                canModify = true,
                repayment = repayment(),
            ),
        )
    }

    @Test
    fun `void entry hidden for terminal voided debt, viewer, member debt and voided repayment`() {
        assertFalse(
            repaymentVoidActionAllowed(
                debt(status = DebtLinkStatuses.VOIDED),
                canModify = true,
                repayment = repayment(),
            ),
        )
        assertFalse(repaymentVoidActionAllowed(debt(), canModify = false, repayment = repayment()))
        assertFalse(
            repaymentVoidActionAllowed(
                debt(counterpartyType = DebtCounterpartyTypes.MEMBER, sourceType = DebtSourceTypes.BILL_SPLIT),
                canModify = true,
                repayment = repayment(),
            ),
        )
        assertFalse(
            repaymentVoidActionAllowed(
                debt(),
                canModify = true,
                repayment = repayment(status = DebtRepaymentStatuses.VOIDED),
            ),
        )
    }
}
