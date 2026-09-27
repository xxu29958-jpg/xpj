package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.ui.screens.settings.syncStatusOverview
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class DebtVoidIntentTest {
    @Test fun bothVoidsPreserveOriginalAcrossUnknownRetryAndRejectWrongReceipt() = runTest {
        for (payment in listOf(false, true)) {
            val fixture = DirectRepaymentTestFixture()
            save(fixture, payment).getOrThrow()
            val original = fixture.dao.rows.values.single()
            assertEquals(1, fixture.engine().drainOnce().failures)
            fixture.api.loseResponse = false
            for (case in listOf("debt", "ledger", "currency", "later_version")) {
                fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
                fixture.api.voidReceiptTransform = { when (case) {
                    "debt" -> it.copy(publicId = "wrong-debt")
                    "ledger" -> it.copy(ledgerId = "wrong-ledger")
                    "currency" -> it.copy(homeCurrencyCode = "JPY")
                    else -> it.copy(rowVersion = original.expectedRowVersion!! + 2)
                } }
                assertEquals(0, fixture.engine().drainOnce().done, case)
                val unverified = fixture.dao.rows.values.single()
                assertEquals(null, unverified.receiptJson, case)
                assertEquals(original.payload, unverified.payload, case)
                assertEquals(original.idempotencyKey, unverified.idempotencyKey, case)
                assertEquals(original.expectedRowVersion, unverified.expectedRowVersion, case)
            }
            fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
            fixture.api.voidReceiptTransform = { it }
            assertEquals(1, fixture.engine().drainOnce().done)
            val stored = fixture.dao.rows.values.single()
            assertEquals(original.payload, stored.payload)
            assertEquals(original.idempotencyKey, stored.idempotencyKey)
            assertEquals(original.expectedRowVersion, stored.expectedRowVersion)
            assertEquals(1, fixture.api.voidFacts.size)
            assertTrue(fixture.api.voidCalls.all { it == fixture.api.voidCalls.first() })
            assertNotNull(stored.receiptJson)
        }
    }

    @Test fun repaymentVoidRejectsClearedUnknownOrNonPositiveOriginalReceiptWithoutReplacingOriginal() = runTest {
        val fixture = DirectRepaymentTestFixture()
        save(fixture, true).getOrThrow()
        val original = fixture.dao.rows.values.single()
        assertEquals(1, fixture.engine().drainOnce().failures)
        fixture.api.loseResponse = false
        for (case in listOf("cleared", "unknown", "zero_remaining", "negative_remaining")) {
            fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
            fixture.api.voidReceiptTransform = { when (case) {
                "cleared" -> it.copy(status = "cleared")
                "unknown" -> it.copy(status = "unknown")
                "zero_remaining" -> it.copy(remainingAmountCents = 0)
                else -> it.copy(remainingAmountCents = -1)
            } }
            assertEquals(0, fixture.engine().drainOnce().done, case)
            val unverified = fixture.dao.rows.values.single()
            assertEquals(null, unverified.receiptJson, case)
            assertEquals(original.payload, unverified.payload, case)
            assertEquals(original.idempotencyKey, unverified.idempotencyKey, case)
            assertEquals(original.expectedRowVersion, unverified.expectedRowVersion, case)
            assertEquals(1, fixture.api.voidFacts.size, case)
        }
        fixture.repository.recover(fixture.binding, fixture.pending(), false).getOrThrow()
        fixture.api.voidReceiptTransform = { it }
        assertEquals(1, fixture.engine().drainOnce().done)
        assertTrue(fixture.api.voidCalls.all { it == fixture.api.voidCalls.first() })
        assertNotNull(fixture.dao.rows.values.single().receiptJson)
    }

    @Test fun nonMoneyVoidsKeepUnknownCurrencyButRejectInvalidReasonTargetAndMemberDebtBeforePublication() = runTest {
        for (payment in listOf(false, true)) {
            val fixture = DirectRepaymentTestFixture()
            val debt = fixture.debt.copy(homeCurrencyCode = "XXX")
            val result = if (payment) fixture.repository.saveRepaymentVoid(fixture.binding, debt, "payment-1", "原原因")
                else fixture.repository.saveVoid(fixture.binding, debt, "原原因")
            assertTrue(result.isSuccess)
            assertTrue(fixture.api.voidCalls.isEmpty())
            assertFalse(fixture.pending().intent is DebtAmountIntent)
            assertFalse(fixture.dao.rows.values.single().payload.contains("amount_cents"))
            val rejected = DirectRepaymentTestFixture()
            assertTrue(rejected.repository.saveVoid(rejected.binding, rejected.debt, " ").isFailure)
            assertTrue(rejected.repository.saveRepaymentVoid(rejected.binding, rejected.debt, "", "原原因").isFailure)
            assertTrue(rejected.repository.saveVoid(rejected.binding, rejected.debt.copy(ledgerId = "foreign"), "原原因").isFailure)
            assertTrue(rejected.repository.saveRepaymentVoid(rejected.binding,
                rejected.debt.copy(counterpartyType = "member"), "payment-1", "原原因").isFailure)
            assertTrue(rejected.dao.rows.isEmpty())
            assertTrue(rejected.api.voidCalls.isEmpty())
        }
    }

    @Test fun everyBindingAxisAndReadonlyCannotAdoptOrRetryOriginalVoid() = runTest {
        val fixture = DirectRepaymentTestFixture()
        save(fixture, true).getOrThrow()
        fixture.engine().drainOnce()
        val pending = fixture.pending()
        val original = fixture.dao.rows.values.single()
        val session = requireNotNull(fixture.session.sessionStore.currentSession())
        for (replacement in replacements(session)) {
            fixture.session.sessionStore.replaceForFixture(replacement)
            assertTrue(fixture.repository.recover(fixture.binding, pending, false).isFailure)
            assertTrue(fixture.repository.recover(fixture.binding, pending, true).isFailure)
            assertTrue(fixture.repository.observeWrites(fixture.binding, fixture.debt.publicId).first().isEmpty())
            assertEquals(original, fixture.dao.rows.values.single())
        }
        fixture.session.sessionStore.replaceForFixture(session.copy(identity = session.identity.copy(role = "viewer")))
        assertTrue(fixture.repository.recover(fixture.binding, pending, false).isFailure)
        assertTrue(save(fixture, false).isFailure)
        assertEquals(original, fixture.dao.rows.values.single())
        assertEquals(1, fixture.api.voidCalls.size)
        fixture.repository.recover(fixture.binding, pending, true).getOrThrow()
        assertEquals(PendingMutationStatus.Abandoned.wireValue, fixture.dao.rows.values.single().status)
        assertEquals(original.payload, fixture.dao.rows.values.single().payload)
    }

    @Test fun acceptedLegacyVoidCannotRetryRebaseOrLoseOriginalWhenLocallyStopped() = runTest {
        val fixture = DirectRepaymentTestFixture()
        save(fixture, true).getOrThrow()
        val original = fixture.dao.rows.values.single()
        fixture.api.refusal = 409 to DEBT_VOID_ORIGINAL_REQUIRES_REVIEW
        assertEquals(1, fixture.engine().drainOnce().failures)
        val pending = fixture.pending()
        assertTrue(pending.requiresReview)
        assertFalse(pending.canRetry)
        assertEquals(null, pending.row.receiptJson)
        assertTrue(fixture.repository.recover(fixture.binding, pending, false).isFailure)
        fixture.repository.recover(fixture.binding, pending, true).getOrThrow()
        val stopped = fixture.dao.rows.values.single()
        assertEquals(original.payload, stopped.payload)
        assertEquals(original.idempotencyKey, stopped.idempotencyKey)
        assertEquals(original.expectedRowVersion, stopped.expectedRowVersion)
        assertEquals(DEBT_VOID_ORIGINAL_REQUIRES_REVIEW, stopped.lastError)
        assertEquals(pending.row.receiptJson, stopped.receiptJson)
        val stoppedIntent = fixture.pending()
        assertEquals(PendingMutationStatus.Abandoned, stoppedIntent.row.status)
        assertFalse(stoppedIntent.requiresReview)
        assertFalse(stoppedIntent.canRetry)
        val overview = syncStatusOverview(OutboxStatus(0, emptyList(), emptyList()), emptyList(), listOf(stoppedIntent))
        assertEquals(0, overview.reviewRequiredCount)
        assertEquals(0, overview.needsActionCount)
        assertEquals(1, overview.stoppedCount)
        assertEquals(0, fixture.engine().drainOnce().attempted)
    }

    private suspend fun save(fixture: DirectRepaymentTestFixture, payment: Boolean) = if (payment) {
        fixture.repository.saveRepaymentVoid(fixture.binding, fixture.debt, "payment-original", "原原因")
    } else fixture.repository.saveVoid(fixture.binding, fixture.debt, "原原因")

    private fun replacements(session: LocalSessionRecord): List<LocalSessionRecord> {
        val other = "30000000-0000-4000-8000-000000000009"
        return listOf(session.copy(serverUrl = "https://foreign.example.test"), session.copy(serverId = other),
            session.copy(dataGeneration = other), session.copy(identity = session.identity.copy(accountPublicId = other)),
            session.copy(identity = session.identity.copy(devicePublicId = other)),
            session.copy(identity = session.identity.copy(ledgerId = "foreign")),
            session.copy(sessionGeneration = "another-session"), session.copy(bindingRevision = "another-binding"))
    }
}
