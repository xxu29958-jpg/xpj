package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * ADR-0049 §7.0 (slice 1A) 列表软分组纯函数 [groupDebtsForList] 的单测 —— 镜像 web `_split_debt_views`：
 * 成员债(home-shape)归家人、外部债+外币成员债归外部，各组 active-first 排序 (open 在前)。
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
            // A foreign-currency member debt falls into the EXTERNAL group (FX fallback).
            debt("m_foreign", DebtCounterpartyTypes.MEMBER, DebtLinkStatuses.OPEN, foreign = true),
        )

        val (members, externals) = groupDebtsForList(debts)

        // Members: open before cleared (active-first); foreign member NOT here.
        assertEquals(listOf("m_open", "m_cleared"), members.map { it.publicId })
        // Externals: opens first (stable order preserved), then voided; foreign member included.
        assertEquals(listOf("e_open", "m_foreign", "e_voided"), externals.map { it.publicId })
    }

    @Test
    fun `empty input yields two empty groups`() {
        val (members, externals) = groupDebtsForList(emptyList())
        assertEquals(emptyList<String>(), members.map { it.publicId })
        assertEquals(emptyList<String>(), externals.map { it.publicId })
    }
}
