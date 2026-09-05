package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtDirections
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DebtCreationRecoveryProjectionTest {
    @Test
    fun recoveryDescribesTheOriginalStoredIntent() = runTest {
        val fixture = DebtCreationFixture()
        val row = failedRow(fixture)

        val summary = requireNotNull(fixture.repository.describePendingCreation(row))

        assertEquals(row.id, summary.intentId)
        assertEquals(DebtCreationPendingState.NeedsAttention, summary.state)
        assertEquals(CurrencyCode.CNY, summary.homeCurrency)
        val draft = requireNotNull(summary.draft)
        assertEquals("小王", draft.counterpartyLabel)
        assertEquals(12_345L, draft.principalAmountCents)
        assertEquals(DebtDirections.OWED_TO_ME, draft.direction)
        assertEquals("出差垫付车费", draft.note)
    }

    @Test
    fun unsupportedPayloadDoesNotInventReadableDetailsOrCurrency() = runTest {
        val fixture = DebtCreationFixture()
        val row = failedRow(fixture)
        val payload = requireNotNull(fixture.adapters.debtCreateAdapter.fromJson(row.payloadJson))
        val unknown = row.copy(payloadJson = fixture.adapters.debtCreateAdapter.toJson(payload.copy(revision = 99)))

        val summary = requireNotNull(fixture.repository.describePendingCreation(unknown))

        assertEquals(row.id, summary.intentId)
        assertEquals(DebtCreationPendingState.Unsupported, summary.state)
        assertNull(summary.draft)
        assertNull(summary.homeCurrency)
    }

    @Test
    fun anotherOwnerLedgerOrMutationCannotBorrowDebtDetails() = runTest {
        val fixture = DebtCreationFixture()
        val row = failedRow(fixture)
        val foreignRows = listOf(
            row.copy(ownerKey = "another-owner"),
            row.copy(ledgerId = "another-ledger"),
            row.copy(type = PendingMutationType.PatchExpense),
        )
        foreignRows.forEach { assertNull(fixture.repository.describePendingCreation(it)) }

        fixture.session.switchLedgerForFixture("next", "另一账本")
        assertNull(fixture.repository.describePendingCreation(row))
    }

    private suspend fun failedRow(fixture: DebtCreationFixture): OutboxRow {
        val receipt = fixture.save().getOrThrow()
        fixture.outbox.markFailed(receipt.intentId, "debt_create_response_unverified")
        return fixture.outbox.observeStatus().first { it.failed.isNotEmpty() }.failed.single()
    }
}
