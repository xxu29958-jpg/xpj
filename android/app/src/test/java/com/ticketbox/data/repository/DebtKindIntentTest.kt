package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class DebtKindIntentTest {
    @Test fun classificationKeepsNonmonetaryMemberHistoricalAndSourceCapabilities() = runTest {
        for (status in listOf("open", "cleared", "voided")) {
            val fixture = DirectRepaymentTestFixture()
            val debt = fixture.debt.copy(status = status, counterpartyType = "member", sourceType = "bill_split",
                homeCurrencyCode = "XXX")
            fixture.repository.saveKind(fixture.binding, debt, "revolving").getOrThrow()
            val original = fixture.dao.rows.values.single()
            assertEquals(debt.rowVersion, original.expectedRowVersion)
            assertFalse(fixture.pending().intent is DebtAmountIntent)
            assertFalse(original.payload.contains("amount_cents"))
            assertTrue(original.payload.contains("XXX"))
            assertTrue(fixture.api.kindCalls.isEmpty())
            assertTrue(fixture.repository.saveRepayment(fixture.binding, fixture.debt, 100).isFailure)
            assertEquals(original, fixture.dao.rows.values.single())
        }
    }

    @Test fun anotherTargetKindCurrencyOrLaterRevisionCannotSettleTheOriginal() = runTest {
        val fixture = DirectRepaymentTestFixture()
        fixture.repository.saveKind(fixture.binding, fixture.debt, "revolving").getOrThrow()
        val original = fixture.dao.rows.values.single()
        fixture.dao.runnableBatches += listOf(fixture.dao.rows.keys.single())
        fixture.engine().drainOnce()
        fixture.api.loseResponse = false
        for (case in listOf("target", "ledger", "kind", "currency", "revision")) {
            fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
            fixture.api.kindReceiptTransform = { when (case) {
                "target" -> it.copy(publicId = "another")
                "ledger" -> it.copy(ledgerId = "another")
                "kind" -> it.copy(debtKind = "one_off")
                "currency" -> it.copy(homeCurrencyCode = "JPY")
                else -> it.copy(rowVersion = it.rowVersion + 1)
            } }
            fixture.dao.runnableBatches += listOf(fixture.dao.rows.keys.single())
            assertEquals(0, fixture.engine().drainOnce().done, case)
            val pending = fixture.dao.rows.values.single()
            assertEquals(null, pending.receiptJson, case)
            assertEquals(original.payload, pending.payload, case)
            assertEquals(original.idempotencyKey, pending.idempotencyKey, case)
        }
        fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
        fixture.api.kindReceiptTransform = { it }
        fixture.dao.runnableBatches += listOf(fixture.dao.rows.keys.single())
        assertEquals(1, fixture.engine().drainOnce().done)
    }

    @Test fun rejectedAdmissionDoesNotPublishOrSendAnotherClassification() = runTest {
        val fixture = DirectRepaymentTestFixture()
        assertTrue(fixture.repository.saveKind(fixture.binding, fixture.debt, "future_kind").isFailure)
        assertTrue(fixture.repository.saveKind(fixture.binding, fixture.debt.copy(ledgerId = "other"), "one_off").isFailure)
        assertTrue(fixture.repository.saveKind(fixture.binding.copy(bindingRevision = "old"), fixture.debt, "one_off").isFailure)
        val readonly = DirectRepaymentTestFixture("viewer")
        assertTrue(readonly.repository.saveKind(readonly.binding, readonly.debt, "one_off").isFailure)
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(readonly.dao.rows.isEmpty())
        assertTrue(fixture.api.kindCalls.isEmpty())
    }

    @Test fun oldAcceptedWithoutReceiptAndReadonlyStopKeepTheOriginalDefinition() = runTest {
        val fixture = DirectRepaymentTestFixture()
        fixture.repository.saveKind(fixture.binding, fixture.debt, "revolving").getOrThrow()
        fixture.api.refusal = 409 to "debt_kind_original_requires_review"
        fixture.dao.runnableBatches += listOf(fixture.dao.rows.keys.single())
        fixture.engine().drainOnce()
        val original = fixture.dao.rows.values.single()
        val pending = fixture.pending()
        assertTrue(pending.requiresReview)
        assertFalse(pending.canRetry)
        val overview = com.ticketbox.ui.screens.settings.syncStatusOverview(
            OutboxStatus(0, emptyList(), listOf(pending.row)), emptyList(), listOf(pending))
        assertEquals(1, overview.reviewRequiredCount)
        assertEquals(0, overview.failedCount)
        val session = requireNotNull(fixture.session.sessionStore.currentSession())
        fixture.session.sessionStore.replaceForFixture(session.copy(identity = session.identity.copy(role = "viewer")))
        fixture.repository.recover(fixture.binding, pending, true).getOrThrow()
        val stopped = fixture.dao.rows.values.single()
        assertEquals(PendingMutationStatus.Abandoned.wireValue, stopped.status)
        assertEquals(original.payload, stopped.payload)
        assertEquals(original.idempotencyKey, stopped.idempotencyKey)
        assertNotNull(fixture.pending().intent)
    }
}
