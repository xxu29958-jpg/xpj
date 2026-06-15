package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberProposalStatuses
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtMappersTest {

    @Test
    fun toDomainMapsAllFieldsIncludingNullableLedger() {
        val dto = DebtDto(
            publicId = "debt-1",
            // A cross-ledger participant view redacts ledger_id to null (§5.2).
            ledgerId = null,
            direction = DebtDirections.I_OWE,
            counterpartyType = DebtCounterpartyTypes.EXTERNAL,
            counterpartyAccountId = null,
            counterpartyLabel = "房东",
            principalAmountCents = 50_000,
            remainingAmountCents = 30_000,
            paidAmountCents = 20_000,
            status = DebtLinkStatuses.OPEN,
            sourceType = DebtSourceTypes.MANUAL,
            sourceId = null,
            homeCurrencyCode = "CNY",
            createdAt = "2026-06-15T00:00:00Z",
            updatedAt = "2026-06-15T01:00:00Z",
            rowVersion = 2,
        )

        val debt = dto.toDomain()

        assertEquals("debt-1", debt.publicId)
        assertNull(debt.ledgerId)
        assertEquals("房东", debt.counterpartyLabel)
        assertEquals(50_000L, debt.principalAmountCents)
        assertEquals(30_000L, debt.remainingAmountCents)
        assertEquals(20_000L, debt.paidAmountCents)
        assertEquals("CNY", debt.homeCurrencyCode)
        assertEquals(2L, debt.rowVersion)
        assertTrue(debt.isOpen)
        assertTrue(debt.isExternal)
        assertFalse(debt.isVoided)
        assertFalse(debt.isBillSplit)
        // An external Debt's DTO carries no viewer role → null (the field defaults absent).
        assertNull(debt.viewerIsDebtor)
    }

    @Test
    fun toDomainComputesVoidedBillSplitMemberFlags() {
        val dto = DebtDto(
            publicId = "debt-2",
            ledgerId = "owner",
            direction = DebtDirections.OWED_TO_ME,
            counterpartyType = DebtCounterpartyTypes.MEMBER,
            counterpartyAccountId = 42,
            counterpartyLabel = null,
            principalAmountCents = 10_000,
            remainingAmountCents = 0,
            paidAmountCents = 10_000,
            status = DebtLinkStatuses.VOIDED,
            sourceType = DebtSourceTypes.BILL_SPLIT,
            sourceId = "inv-1",
            homeCurrencyCode = "CNY",
            createdAt = "2026-06-15T00:00:00Z",
            updatedAt = "2026-06-15T00:00:00Z",
            rowVersion = 3,
        )

        val debt = dto.toDomain()

        assertEquals(42L, debt.counterpartyAccountId)
        assertEquals("inv-1", debt.sourceId)
        assertTrue(debt.isVoided)
        assertTrue(debt.isBillSplit)
        assertFalse(debt.isExternal)
        assertFalse(debt.isOpen)
        assertFalse(debt.isCleared)
    }

    @Test
    fun toCreateRequestForcesExternalManualAndTrimsLabel() {
        val request = DebtDraft(
            direction = DebtDirections.OWED_TO_ME,
            counterpartyLabel = "  小王  ",
            principalAmountCents = 12_345,
        ).toCreateRequest()

        assertEquals(DebtDirections.OWED_TO_ME, request.direction)
        // Public create is external/manual only; member Debt is server-side (§5.2).
        assertEquals(DebtCounterpartyTypes.EXTERNAL, request.counterpartyType)
        assertEquals(DebtSourceTypes.MANUAL, request.sourceType)
        assertEquals("小王", request.counterpartyLabel)
        assertEquals(12_345L, request.principalAmountCents)
    }

    @Test
    fun proposalToDomainMapsAllFields() {
        val dto = MemberRepaymentProposalDto(
            publicId = "p1",
            debtPublicId = "d1",
            status = MemberProposalStatuses.PARTIALLY_CONFIRMED,
            proposedAmountCents = 20_000,
            confirmedAmountCents = 15_000,
            homeCurrencyCode = "CNY",
            originalCurrencyCode = null,
            originalAmountMinor = null,
            paidAt = "2026-06-16T00:00:00Z",
            note = "微信转账",
            expiresAt = "2026-07-16T00:00:00Z",
            createdAt = "2026-06-16T00:00:00Z",
            resolvedAt = "2026-06-16T01:00:00Z",
            supersedesProposalPublicId = "p0",
            committedRepaymentPublicId = "r1",
        )

        val proposal = dto.toDomain()

        assertEquals("p1", proposal.publicId)
        assertEquals("d1", proposal.debtPublicId)
        assertEquals(20_000L, proposal.proposedAmountCents)
        assertEquals(15_000L, proposal.confirmedAmountCents)
        assertEquals("微信转账", proposal.note)
        assertEquals("p0", proposal.supersedesProposalPublicId)
        assertEquals("r1", proposal.committedRepaymentPublicId)
        assertFalse(proposal.isPending)
        assertTrue(proposal.isPartiallyConfirmed)
        assertTrue(proposal.isResolvedByConfirm)
    }

    @Test
    fun viewerIsDebtorMapsServerAuthoritativeRole() {
        // The client does NOT derive the debtor/creditor role (it can't — no own account id, and
        // ledger membership doesn't distinguish a same-ledger owner from a same-ledger counterparty).
        // It reads the server-authoritative DebtResponse.viewer_is_debtor verbatim.
        assertEquals(true, memberDebt(viewerIsDebtor = true).viewerIsDebtor)
        assertEquals(false, memberDebt(viewerIsDebtor = true).viewerIsCreditor)
        assertEquals(false, memberDebt(viewerIsDebtor = false).viewerIsDebtor)
        assertEquals(true, memberDebt(viewerIsDebtor = false).viewerIsCreditor)
        // null (external Debt / not a party / non-participant path) → both null.
        assertNull(memberDebt(viewerIsDebtor = null).viewerIsDebtor)
        assertNull(memberDebt(viewerIsDebtor = null).viewerIsCreditor)
    }

    private fun memberDebt(viewerIsDebtor: Boolean?) = DebtDto(
        publicId = "d1",
        ledgerId = "owner",
        direction = DebtDirections.I_OWE,
        counterpartyType = DebtCounterpartyTypes.MEMBER,
        counterpartyAccountId = 42,
        counterpartyLabel = "家人",
        principalAmountCents = 10_000,
        remainingAmountCents = 10_000,
        paidAmountCents = 0,
        status = DebtLinkStatuses.OPEN,
        sourceType = DebtSourceTypes.BILL_SPLIT,
        sourceId = "inv-1",
        homeCurrencyCode = "CNY",
        createdAt = "2026-06-16T00:00:00Z",
        updatedAt = "2026-06-16T00:00:00Z",
        rowVersion = 1,
        viewerIsDebtor = viewerIsDebtor,
    ).toDomain()
}
