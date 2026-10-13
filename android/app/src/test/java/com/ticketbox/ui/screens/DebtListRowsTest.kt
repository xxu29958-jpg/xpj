package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 家人/外部分组由真实关系决定，币种不改变关系；各组保留未结在前的顺序。
 */
class DebtListRowsTest {

    private fun debt(
        publicId: String,
        counterpartyType: String,
        status: String,
        foreign: Boolean = false,
    ): Debt = Debt(
        publicId = publicId,
        ledgerId = "owner",
        direction = DebtDirections.I_OWE,
        counterpartyType = counterpartyType,
        counterpartyAccountId = if (counterpartyType == DebtCounterpartyTypes.MEMBER) 7L else null,
        counterpartyLabel = "对手方",
        principalAmountCents = 10_000,
        remainingAmountCents = 10_000,
        paidAmountCents = 0,
        status = status,
        sourceType = if (counterpartyType == DebtCounterpartyTypes.MEMBER) {
            DebtSourceTypes.BILL_SPLIT
        } else {
            DebtSourceTypes.MANUAL
        },
        sourceId = null,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = if (foreign) "USD" else null,
        originalAmountMinor = if (foreign) 1_500 else null,
        createdAt = "2026-06-18T00:00:00Z",
        updatedAt = "2026-06-18T00:00:00Z",
        rowVersion = 1,
    )

    @Test
    fun `groups family before external, active first within each`() {
        val debts = listOf(
            debt("m_cleared", DebtCounterpartyTypes.MEMBER, DebtLinkStatuses.CLEARED),
            debt("e_voided", DebtCounterpartyTypes.EXTERNAL, DebtLinkStatuses.VOIDED),
            debt("m_open", DebtCounterpartyTypes.MEMBER, DebtLinkStatuses.OPEN),
            debt("e_open", DebtCounterpartyTypes.EXTERNAL, DebtLinkStatuses.OPEN),
            debt("m_foreign", DebtCounterpartyTypes.MEMBER, DebtLinkStatuses.OPEN, foreign = true),
        )

        val (members, externals) = groupDebtsForList(debts)

        assertEquals(listOf("m_open", "m_foreign", "m_cleared"), members.map { it.publicId })
        assertEquals(listOf("e_open", "e_voided"), externals.map { it.publicId })
    }

    @Test
    fun `empty input yields two empty groups`() {
        val (members, externals) = groupDebtsForList(emptyList())
        assertEquals(emptyList<String>(), members.map { it.publicId })
        assertEquals(emptyList<String>(), externals.map { it.publicId })
    }

    @Test
    fun `totals use participant direction and frozen currency without third party or closed balances`() {
        val member = debt("member", DebtCounterpartyTypes.MEMBER, DebtLinkStatuses.OPEN)
        val external = debt("external", DebtCounterpartyTypes.EXTERNAL, DebtLinkStatuses.OPEN)
        val rows = listOf(
            member.copy(viewerIsDebtor = false, remainingAmountCents = 3800, homeCurrencyCode = "JPY"),
            member.copy(publicId = "foreign", viewerIsDebtor = false, remainingAmountCents = 700,
                homeCurrencyCode = "JPY", originalCurrencyCode = "USD", originalAmountMinor = 500),
            member.copy(publicId = "third-party", viewerIsDebtor = null),
            external.copy(remainingAmountCents = 116000),
            external.copy(publicId = "closed", status = DebtLinkStatuses.CLEARED),
            external.copy(publicId = "voided", status = DebtLinkStatuses.VOIDED),
            external.copy(publicId = "unknown-currency", homeCurrencyCode = "VND", remainingAmountCents = 2000),
        )
        assertEquals(listOf(
            DebtListTotal(DebtDirections.OWED_TO_ME, "JPY", 2, 4500),
            DebtListTotal(DebtDirections.I_OWE, "CNY", 1, 116000),
            DebtListTotal(DebtDirections.I_OWE, "VND", 1, 2000),
        ), debtListTotals(rows))
        assertEquals(emptyList<DebtListTotal>(), debtListTotals(listOf(member)))
    }

    @Test
    fun `an overflowing total does not become a negative balance`() {
        val row = debt("large", DebtCounterpartyTypes.EXTERNAL, DebtLinkStatuses.OPEN)
            .copy(remainingAmountCents = Long.MAX_VALUE)
        assertEquals(DebtListTotal(DebtDirections.I_OWE, "CNY", 2, null), debtListTotals(listOf(row, row)).single())
    }
}
